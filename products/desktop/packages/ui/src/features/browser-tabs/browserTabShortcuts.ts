export function shouldHandleBrowserTabSwitch(
  event: Pick<KeyboardEvent, "ctrlKey" | "metaKey">,
  macPlatform: boolean,
): boolean {
  return !macPlatform || !event.ctrlKey || event.metaKey;
}
