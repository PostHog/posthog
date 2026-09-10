import type { Icon } from "@phosphor-icons/react";
import { GithubLogoIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import type { ComponentProps, ReactElement, ReactNode } from "react";
import { forwardRef } from "react";

/**
 * DOM attribute carrying the chip's GitHub URL. The conversation context menu
 * reads it (via `closest()`) so "Copy" can copy the link of a right-clicked
 * chip, which is otherwise unreachable from a text selection.
 */
export const GITHUB_REF_URL_ATTR = "data-github-ref-url";

interface GithubRefChipLinkProps
  extends Omit<ComponentProps<typeof Button>, "children"> {
  href: string;
  icon: Icon;
  /** Names the icon for screen readers. Omit when the icon says nothing extra. */
  iconLabel?: string;
  toneClass?: string;
  /** Keeps a trailing `#number` visible when the label truncates. */
  preservePrNumber?: boolean;
  children: ReactNode;
}

/**
 * Truncation removes the end of a label, which for `owner/repo#number` is the
 * number that tells two pull requests apart. Only labels that end in a number
 * qualify: `#12 - Title` already keeps its number at the front.
 */
function endsWithRefNumber(label: ReactNode): boolean {
  return typeof label === "string" && /#\d+$/.test(label);
}

/**
 * The chip every GitHub reference renders as: a quill button whose element is
 * the link itself, so the chip is one thing to click and one thing to tab to.
 *
 * Forwards button props and its ref, so a tooltip or menu can drive it through
 * `render`.
 */
export const GithubRefChipLink = forwardRef<
  HTMLButtonElement,
  GithubRefChipLinkProps
>(function GithubRefChipLink(
  {
    href,
    icon: RefIcon,
    iconLabel,
    toneClass,
    preservePrNumber,
    children,
    ...buttonProps
  },
  ref,
) {
  // A right-to-left box puts the ellipsis at the start, so the trailing number
  // survives truncation. The inner isolate keeps the text itself left-to-right.
  // The label stays one text node on purpose: a number in its own flex item
  // puts a line break into copied text.
  const ellipsisAtStart = preservePrNumber && endsWithRefNumber(children);
  return (
    <Button
      ref={ref}
      variant="outline"
      size="sm"
      // The chip is a link, so it keeps link semantics and Base UI must not
      // expect a native <button>.
      nativeButton={false}
      render={
        <a
          {...{ [GITHUB_REF_URL_ATTR]: href }}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
        />
      }
      {...buttonProps}
      className={cn(
        "cli-file-mention focus-visible:-outline-offset-1 mx-0.5 inline-block max-w-full cursor-pointer! select-text whitespace-nowrap pl-1.5 align-baseline leading-[1.375rem] no-underline",
        buttonProps.className,
      )}
    >
      <RefIcon
        size={12}
        weight="bold"
        className={cn("mr-1 inline-block align-[-0.125em]", toneClass)}
        aria-label={iconLabel}
        aria-hidden={iconLabel ? undefined : true}
        role={iconLabel ? "img" : undefined}
      />
      <span
        // 1rem is the icon and its margin, which share the chip's content box
        // with the label. Without that subtraction the label paints past the
        // chip edge in a narrow panel instead of truncating.
        className={cn(
          "inline-block max-w-[min(16rem,calc(100%-1rem))] truncate align-top",
          toneClass,
        )}
        dir={ellipsisAtStart ? "rtl" : undefined}
      >
        {ellipsisAtStart ? <span dir="ltr">{children}</span> : children}
      </span>
    </Button>
  );
});

/**
 * A GitHub reference with no live status behind it: issue links, and stored
 * mentions that render from saved text rather than from a fetch. `PrRefChip`
 * is the one that reports a pull request's lifecycle.
 */
export function GithubRefChip({
  href,
  kind,
  children,
}: {
  href: string;
  kind: "issue" | "pr";
  children: ReactNode;
}): ReactElement {
  return (
    <GithubRefChipLink
      href={href}
      icon={kind === "pr" ? GitPullRequestIcon : GithubLogoIcon}
      preservePrNumber={kind === "pr"}
    >
      {children}
    </GithubRefChipLink>
  );
}
