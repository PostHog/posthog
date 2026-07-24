/**
 * Animated three-dot ellipsis used while the inbox is warming up.
 * Requires the `inbox-ellipsis-dot` CSS class (defined in inbox styles).
 */
export function AnimatedEllipsis() {
  return (
    <span aria-hidden>
      <span className="inline-flex items-end gap-px leading-none">
        <span className="inbox-ellipsis-dot">.</span>
        <span className="inbox-ellipsis-dot">.</span>
        <span className="inbox-ellipsis-dot">.</span>
      </span>
    </span>
  );
}
