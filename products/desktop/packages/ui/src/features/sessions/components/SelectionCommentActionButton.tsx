import { useThemeStore } from "@posthog/ui/shell/themeStore";
import type { ComponentPropsWithoutRef, CSSProperties, ReactNode } from "react";
import { forwardRef, useEffect } from "react";
import {
  COMMENT_ACTION_BUTTON_THEMES,
  type CommentSurfaceTheme,
  commentActionButtonCss,
} from "./selectionCommentAction";

const STYLE_ELEMENT_ID = "ph-comment-action-styles";

// The app renders the same stylesheet the sandboxed iframes inject, so the
// action cannot drift between markdown artifacts, HTML artifacts and canvases.
function useCommentActionStyles(): void {
  useEffect(() => {
    if (document.getElementById(STYLE_ELEMENT_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ELEMENT_ID;
    style.textContent = commentActionButtonCss();
    document.head.appendChild(style);
  }, []);
}

function paletteVars(theme: CommentSurfaceTheme): CSSProperties {
  const palette = COMMENT_ACTION_BUTTON_THEMES[theme];
  return {
    "--ph-comment-action-bg": palette.background,
    "--ph-comment-action-fg": palette.color,
    "--ph-comment-action-border": palette.border,
    "--ph-comment-action-hover": palette.hoverBackground,
    "--ph-comment-action-shadow": palette.shadow,
  } as CSSProperties;
}

interface SelectionCommentActionButtonProps
  extends Omit<ComponentPropsWithoutRef<"button">, "style" | "className"> {
  label: string;
  /** Icon-only trigger: a square button with no visible label. */
  iconOnly?: boolean;
  children: ReactNode;
  position: { top: number; left: number };
}

/**
 * The floating action offered next to a text selection. Deliberately not a
 * Quill button: it has to look identical inside sandboxed artifact iframes,
 * which cannot load the app's stylesheets, so both sides share one class and
 * one palette.
 */
export const SelectionCommentActionButton = forwardRef<
  HTMLButtonElement,
  SelectionCommentActionButtonProps
>(function SelectionCommentActionButton(
  { label, iconOnly = false, children, position, ...buttonProps },
  ref,
) {
  useCommentActionStyles();
  const theme = useThemeStore(
    (state): CommentSurfaceTheme => (state.isDarkMode ? "dark" : "light"),
  );
  return (
    <button
      // Spread first: tooltip triggers attach their own handlers and ARIA here.
      {...buttonProps}
      ref={ref}
      type="button"
      aria-label={label}
      data-selection-comment-overlay=""
      className={
        iconOnly
          ? "ph-comment-action-button ph-comment-action-button--icon"
          : "ph-comment-action-button"
      }
      style={{ ...paletteVars(theme), ...position }}
    >
      {children}
    </button>
  );
});
