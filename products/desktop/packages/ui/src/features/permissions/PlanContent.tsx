import {
  ArrowsIn,
  ArrowsOut,
  Check,
  Copy,
  ListChecks,
  X,
} from "@phosphor-icons/react";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PlanSectionComment } from "./PlanSectionComment";
import { splitPlanSections, usePlanReviewStore } from "./planReview";

const planScrollPosition = new Map<string, number>();

interface PlanContentProps {
  id: string;
  plan: string;
  reviewable?: boolean;
}

export function PlanContent({
  id,
  plan,
  reviewable = false,
}: PlanContentProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [openSectionId, setOpenSectionId] = useState<string | null>(null);
  const [editingCommentId, setEditingCommentId] = useState<string | null>(null);
  const sections = useMemo(() => splitPlanSections(plan), [plan]);
  const comments = usePlanReviewStore((state) => state.comments[id] ?? []);
  const addComment = usePlanReviewStore((state) => state.addComment);
  const updateComment = usePlanReviewStore((state) => state.updateComment);
  const removeComment = usePlanReviewStore((state) => state.removeComment);

  useEffect(() => {
    if (reviewable) usePlanReviewStore.getState().reconcile(id, sections);
  }, [id, reviewable, sections]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(plan);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard write failed
    }
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const position = planScrollPosition.get(id);
    if (position !== undefined) {
      el.scrollTop = position;
    }

    const handleScroll = () => {
      planScrollPosition.set(id, el.scrollTop);
    };

    el.addEventListener("scroll", handleScroll, { passive: true });

    return () => {
      el.removeEventListener("scroll", handleScroll);
    };
  }, [id]);

  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsFullscreen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  const markdown = sections.map((section) => {
    const sectionComments = comments.filter(
      (comment) => comment.sectionId === section.id,
    );
    const isCommentOpen = openSectionId === section.id;

    return (
      <section
        key={section.id}
        id={`${id}-${section.id}`}
        data-plan-section={section.id}
        className="group/plan-section scroll-mt-4"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {section.content}
            </ReactMarkdown>
          </div>
          {reviewable && (
            <button
              type="button"
              className="mt-1 shrink-0 rounded-sm px-1.5 py-0.5 text-[11px] text-gray-10 opacity-0 transition-opacity hover:bg-gray-3 hover:text-gray-12 focus:opacity-100 group-hover/plan-section:opacity-100"
              onClick={() => {
                setEditingCommentId(null);
                setOpenSectionId(isCommentOpen ? null : section.id);
              }}
              aria-label={`Comment on ${section.title}`}
              data-attr="plan-section-comment"
            >
              Comment
            </button>
          )}
        </div>

        {sectionComments.map((comment) => (
          <div
            key={comment.id}
            className={`mt-2 rounded-md border px-2.5 py-2 text-[13px] ${comment.stale ? "border-orange-6 bg-orange-2" : "border-gray-6 bg-gray-2"}`}
          >
            {comment.stale && (
              <Text as="div" size="1" color="orange" className="mb-1">
                This comment refers to an earlier version of the plan.
              </Text>
            )}
            {editingCommentId === comment.id ? (
              <PlanSectionComment
                initialText={comment.text}
                onDismiss={() => setEditingCommentId(null)}
                onSubmit={(text) => {
                  updateComment(id, comment.id, text, section);
                  setEditingCommentId(null);
                }}
              />
            ) : (
              <>
                <Text as="div" className="whitespace-pre-wrap text-gray-12">
                  {comment.text}
                </Text>
                {reviewable && (
                  <Flex gap="2" className="mt-1">
                    <button
                      type="button"
                      className="text-[11px] text-gray-10 hover:text-gray-12"
                      onClick={() => setEditingCommentId(comment.id)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="text-[11px] text-gray-10 hover:text-gray-12"
                      onClick={() => removeComment(id, comment.id)}
                    >
                      Remove
                    </button>
                  </Flex>
                )}
              </>
            )}
          </div>
        ))}

        {reviewable && isCommentOpen && (
          <PlanSectionComment
            onDismiss={() => setOpenSectionId(null)}
            onSubmit={(text) => {
              addComment(id, {
                sectionId: section.id,
                sectionTitle: section.title,
                sectionContent: section.content,
                text,
              });
              setOpenSectionId(null);
            }}
          />
        )}
      </section>
    );
  });
  const missingComments = comments.filter(
    (comment) =>
      comment.stale &&
      !sections.some((section) => section.id === comment.sectionId),
  );
  if (missingComments.length > 0) {
    markdown.push(
      <div key="stale-plan-comments" className="mt-3">
        <Text as="div" size="1" color="orange" className="mb-1">
          Review comments from an earlier plan version
        </Text>
        {missingComments.map((comment) => (
          <div
            key={comment.id}
            className="mt-2 rounded-md border border-orange-6 bg-orange-2 px-2.5 py-2 text-[13px]"
          >
            {editingCommentId === comment.id ? (
              <PlanSectionComment
                initialText={comment.text}
                onDismiss={() => setEditingCommentId(null)}
                onSubmit={(text) => {
                  updateComment(id, comment.id, text);
                  setEditingCommentId(null);
                }}
              />
            ) : (
              <>
                <Text as="div" className="text-gray-12">
                  {comment.text}
                </Text>
                {reviewable && (
                  <Flex gap="2" className="mt-1">
                    <button
                      type="button"
                      className="text-[11px] text-gray-10 hover:text-gray-12"
                      onClick={() => removeComment(id, comment.id)}
                    >
                      Remove
                    </button>
                  </Flex>
                )}
              </>
            )}
          </div>
        ))}
      </div>,
    );
  }

  if (isFullscreen) {
    const portalTarget = document.getElementById("fullscreen-portal");
    if (portalTarget) {
      return (
        <>
          <Flex justify="end" className="py-0.5">
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => setIsFullscreen(false)}
              title="Exit fullscreen"
              aria-label="Exit fullscreen"
            >
              <ArrowsIn size={12} />
            </IconButton>
          </Flex>

          {createPortal(
            <Box className="pointer-events-auto absolute inset-0 flex flex-col bg-blue-2">
              <Flex
                align="center"
                justify="between"
                className="border-blue-6 border-b px-4 py-2"
              >
                <Flex align="center" gap="2">
                  <ListChecks size={14} className="text-blue-11" />
                  <Text className="text-blue-11 text-sm">Plan</Text>
                </Flex>
                <Flex align="center" gap="2">
                  <Tooltip
                    content={copied ? "Copied!" : "Copy plan to clipboard"}
                    side="bottom"
                  >
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="gray"
                      onClick={handleCopy}
                      aria-label="Copy plan to clipboard"
                    >
                      {copied ? <Check size={12} /> : <Copy size={12} />}
                    </IconButton>
                  </Tooltip>
                  <Tooltip content="Exit fullscreen (Escape)" side="bottom">
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="gray"
                      onClick={() => setIsFullscreen(false)}
                      aria-label="Exit fullscreen"
                    >
                      <X size={14} />
                    </IconButton>
                  </Tooltip>
                </Flex>
              </Flex>

              <Box
                ref={scrollRef}
                className="plan-markdown flex-1 overflow-y-auto p-6 text-blue-12"
              >
                {markdown}
              </Box>
            </Box>,
            portalTarget,
          )}
        </>
      );
    }
  }

  return (
    <Box
      ref={scrollRef}
      className="relative max-h-[50vh] max-w-[750px] overflow-y-auto rounded-lg border-2 border-blue-6 bg-blue-2 p-4"
    >
      <Flex gap="2" className="sticky top-0 z-10 float-right">
        <Tooltip
          content={copied ? "Copied!" : "Copy plan to clipboard"}
          side="bottom"
        >
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            onClick={handleCopy}
            aria-label="Copy plan to clipboard"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </IconButton>
        </Tooltip>
        <Tooltip content="Expand to fullscreen" side="bottom">
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            onClick={() => setIsFullscreen(true)}
            aria-label="Expand to fullscreen"
          >
            <ArrowsOut size={12} />
          </IconButton>
        </Tooltip>
      </Flex>

      <Box className="plan-markdown text-blue-12">{markdown}</Box>
    </Box>
  );
}
