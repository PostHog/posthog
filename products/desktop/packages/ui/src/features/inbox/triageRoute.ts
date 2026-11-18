/** Triage is a place, so it has a URL: it survives a reload, restores with the
 *  rail, and a report it opens can point back at it. */
export const INBOX_TRIAGE_ROUTE = "/inbox/triage";

export function isInboxTriagePath(pathname: string): boolean {
  return (
    pathname === INBOX_TRIAGE_ROUTE || pathname === `${INBOX_TRIAGE_ROUTE}/`
  );
}
