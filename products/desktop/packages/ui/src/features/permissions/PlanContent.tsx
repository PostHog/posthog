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
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const planScrollPosition = new Map<string, number>();

interface PlanContentProps {
  id: string;
  plan: string;
}

export function PlanContent({ id, plan }: PlanContentProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);

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

  const markdown = (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{plan}</ReactMarkdown>
  );

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
          >
            <ArrowsOut size={12} />
          </IconButton>
        </Tooltip>
      </Flex>

      <Box className="plan-markdown text-blue-12">{markdown}</Box>
    </Box>
  );
}
