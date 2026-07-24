import { CaretDown, CaretUp } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { Box } from "@radix-ui/themes";
import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useRef,
  useState,
} from "react";

const COLLAPSED_MAX_HEIGHT = 120;

interface CollapsibleMessageContentProps {
  children: ReactNode;
  className?: string;
  /** Extra classes for the inner content box (e.g. per-caller typography). */
  contentClassName?: string;
  style?: CSSProperties;
}

export function CollapsibleMessageContent({
  children,
  className,
  contentClassName,
  style,
}: CollapsibleMessageContentProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const observerRef = useRef<ResizeObserver | null>(null);

  // Callback ref (not a mount effect) so it measures before paint; the observer
  // re-checks on reflow and lazy `content-visibility` layout.
  const measureRef = useCallback((el: HTMLDivElement | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!el) return;
    const measure = () =>
      setIsOverflowing(el.scrollHeight > COLLAPSED_MAX_HEIGHT);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    observerRef.current = observer;
  }, []);

  return (
    <Box className={className} style={style}>
      {/* Paint-only mask fades just the text — no background color to match, no
          full-width band past ragged text. */}
      <Box
        ref={measureRef}
        className={cn(
          "overflow-hidden [&>*:last-child]:mb-0",
          !isExpanded &&
            isOverflowing &&
            "[mask-image:linear-gradient(to_bottom,black_45%,transparent)]",
          contentClassName,
        )}
        style={
          !isExpanded && isOverflowing
            ? { maxHeight: COLLAPSED_MAX_HEIGHT }
            : undefined
        }
      >
        {children}
      </Box>
      {isOverflowing && (
        <button
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
          className="mt-1 inline-flex items-center gap-1 text-[12px] text-accent-11 hover:text-accent-12"
        >
          {isExpanded ? (
            <>
              <CaretUp size={12} />
              Show less
            </>
          ) : (
            <>
              <CaretDown size={12} />
              Show more
            </>
          )}
        </button>
      )}
    </Box>
  );
}
