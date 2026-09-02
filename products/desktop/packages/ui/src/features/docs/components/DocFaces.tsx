import { caretColor, type RemoteCaret } from "../collab/remoteCarets";
import { DocRefHover } from "../extensions/inline/DocRefCard";

/** Room for four faces; past that the rest are counted. */
const MAX_FACES = 4;

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

/**
 * Who else is in this doc, as an overlapping stack of faces.
 *
 * Each face carries its owner's caret colour, so the person in the header and
 * the caret in the text read as the same person. Pressing one goes to them.
 */
export function DocFaces({
  peers,
  onJump,
}: {
  peers: RemoteCaret[];
  onJump: (clientId: string) => void;
}) {
  const shown = peers.slice(0, MAX_FACES);
  const hidden = peers.length - shown.length;

  return (
    <div className="flex shrink-0 items-center">
      {shown.map((peer) => (
        <DocRefHover
          key={peer.clientId}
          nativeButton
          card={{
            title: peer.userName,
            action: {
              label: "Jump to their cursor",
              onSelect: () => onJump(peer.clientId),
            },
          }}
          trigger={
            <button
              type="button"
              onClick={() => onJump(peer.clientId)}
              className="-ml-1 flex size-[17px] cursor-pointer items-center justify-center rounded-full border border-(--gray-1) font-medium text-[7.5px] text-white first:ml-0"
              style={{ backgroundColor: caretColor(peer.clientId) }}
            >
              {initials(peer.userName)}
            </button>
          }
        />
      ))}
      {hidden > 0 ? (
        <span className="ml-1.5 text-(--gray-9) text-[9.5px]">+{hidden}</span>
      ) : null}
    </div>
  );
}
