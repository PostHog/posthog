import { type KeyboardEvent, type RefObject, useEffect } from "react";

const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Only Tab pressed inside the dialog is caught, so menus portaled out of it
// keep their own focus.
export function useDialogFocus(
  dialogRef: RefObject<HTMLElement | null>,
): (event: KeyboardEvent<HTMLElement>) => void {
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    if (!dialog.contains(document.activeElement)) {
      (dialog.querySelector<HTMLElement>(TABBABLE) ?? dialog).focus();
    }
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [dialogRef]);

  return (event) => {
    if (event.key !== "Tab" || !dialogRef.current) return;
    const tabbable = [
      ...dialogRef.current.querySelectorAll<HTMLElement>(TABBABLE),
    ].filter((el) => el.offsetParent !== null);
    const first = tabbable[0];
    const last = tabbable[tabbable.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
}
