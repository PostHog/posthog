from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from langgraph.checkpoint.serde.types import TASKS

from products.posthog_ai.backend.models.assistant import (
    Conversation,
    ConversationCheckpoint,
    ConversationCheckpointBlob,
    ConversationCheckpointWrite,
)


@dataclass(frozen=True)
class CompactionResult:
    compacted: bool
    checkpoints_deleted: int = 0
    blobs_deleted: int = 0
    namespaces: int = 0

    def __add__(self, other: "CompactionResult") -> "CompactionResult":
        return CompactionResult(
            compacted=self.compacted or other.compacted,
            checkpoints_deleted=self.checkpoints_deleted + other.checkpoints_deleted,
            blobs_deleted=self.blobs_deleted + other.blobs_deleted,
            namespaces=self.namespaces + other.namespaces,
        )


def _is_safe_to_compact(conversation: Conversation) -> bool:
    """A thread is only safe to collapse when it has finished a turn and has no pending approval.

    Compaction nulls the tip's parent, which drops the parent's pending Sends — so any thread
    that is mid-run, being cancelled, or paused at an approval interrupt must be left untouched."""
    if conversation.status != Conversation.Status.IDLE:
        return False
    return not any(
        isinstance(decision, dict) and decision.get("decision_status") == "pending"
        for decision in (conversation.approval_decisions or {}).values()
    )


def compact_thread(thread_id: str, checkpoint_ns: str = "") -> CompactionResult:
    """Collapse a conversation thread to its latest checkpoint, keeping it fully resumable.

    The latest checkpoint plus the blobs its `channel_versions` reference is a complete,
    resumable snapshot (the accumulating `messages` channel stores the whole history at its
    latest version). This relies on every channel persisting a *complete* value per version, which
    `DjangoCheckpointer._put` does today. A langgraph `DeltaChannel` would break it — the tip is
    rarely a delta snapshot point, so keeping only the tip would silently reconstruct that channel
    as empty. Max uses no delta channels; do not adopt one without revisiting this. Every older
    checkpoint, superseded blob version, and stale write is dead weight. Two storage traps make
    this more than a delete:

    - The `parent_checkpoint` self-FK cascades, so deleting an ancestor would take the tip with
      it. We null the tip's parent first to detach it from the chain.
    - A blob is owned (FK, cascade) by the checkpoint that created its version, which may be an
      ancestor. We reassign the blobs the tip still references to the tip before deleting, so
      the cascade can't remove a blob the tip needs.

    Only checkpoints strictly older than the chosen tip are deleted, so a thread that resumes
    between selecting the tip and deleting is never corrupted (the newer checkpoint is left in
    place and its parent chain stays valid)."""
    with transaction.atomic():
        # nosemgrep: idor-lookup-without-team (internal LangGraph checkpoint maintenance)
        conversation = Conversation.objects.select_for_update().filter(pk=thread_id).first()
        if conversation is None or not _is_safe_to_compact(conversation):
            return CompactionResult(compacted=False)

        # `checkpoint__isnull=False` mirrors the read path (`DjangoCheckpointer._get_checkpoint_qs`):
        # `put_writes` can create a checkpoint row before `put` fills in its JSON, so a higher-id
        # placeholder with a null checkpoint must never be chosen as the tip — doing so would
        # reassign no blobs and delete the real latest state beneath it.
        tip = (
            ConversationCheckpoint.objects.filter(
                thread_id=thread_id, checkpoint_ns=checkpoint_ns, checkpoint__isnull=False
            )
            .order_by("-id")
            .first()
        )
        if tip is None:
            return CompactionResult(compacted=False)

        # A tip whose parent still holds pending Sends (the TASKS channel) would lose that
        # routing when we detach the parent. Leave such a thread intact rather than risk an
        # unresumable tip; an idle, fully-completed turn has no such writes.
        if (
            tip.parent_checkpoint_id is not None
            and ConversationCheckpointWrite.objects.filter(
                checkpoint_id=tip.parent_checkpoint_id, channel=TASKS
            ).exists()
        ):
            return CompactionResult(compacted=False)

        # `or {}` is for the type checker only — the tip is guaranteed non-null by the filter above.
        channel_versions: dict[str, object] = (tip.checkpoint or {}).get("channel_versions", {})
        if channel_versions:
            referenced = Q()
            for channel, version in channel_versions.items():
                referenced |= Q(channel=channel, version=str(version))
            # Scope by the *owning checkpoint's* namespace, not the blob's own checkpoint_ns:
            # DjangoCheckpointer._put writes every blob with the default checkpoint_ns="" regardless
            # of its checkpoint's namespace, so filtering on the blob's field would match nothing for
            # a subgraph and let the cascade delete blobs the tip still references. Joining through the
            # owning checkpoint keeps the reassignment inside this namespace — it never touches another
            # namespace's blobs.
            ConversationCheckpointBlob.objects.filter(
                Q(checkpoint__thread_id=thread_id, checkpoint__checkpoint_ns=checkpoint_ns) & referenced
            ).update(checkpoint=tip)

        ConversationCheckpoint.objects.filter(pk=tip.pk).update(parent_checkpoint=None)

        _, deleted_by_model = ConversationCheckpoint.objects.filter(
            thread_id=thread_id, checkpoint_ns=checkpoint_ns, id__lt=tip.id
        ).delete()

    checkpoints_deleted = deleted_by_model.get(ConversationCheckpoint._meta.label, 0)
    blobs_deleted = deleted_by_model.get(ConversationCheckpointBlob._meta.label, 0)
    return CompactionResult(
        compacted=checkpoints_deleted > 0,
        checkpoints_deleted=checkpoints_deleted,
        blobs_deleted=blobs_deleted,
    )


def compact_conversation(thread_id: str) -> CompactionResult:
    """Compact every checkpoint namespace of a conversation, not just the root graph.

    Max runs subgraphs (taxonomy, tools, deep-research, ...), each persisting checkpoints under its
    own `checkpoint_ns`. `compact_thread` collapses a single namespace, so compacting only the root
    ("") leaves every subgraph namespace untouched — most of a real conversation's checkpoints."""
    # nosemgrep: idor-lookup-without-team (internal LangGraph checkpoint maintenance)
    namespaces = list(
        ConversationCheckpoint.objects.filter(thread_id=thread_id).values_list("checkpoint_ns", flat=True).distinct()
    )
    # Seed the namespace count here so callers (e.g. the admin audit log) don't re-query it.
    result = CompactionResult(compacted=False, namespaces=len(namespaces))
    for checkpoint_ns in namespaces:
        result += compact_thread(thread_id, checkpoint_ns)
    return result
