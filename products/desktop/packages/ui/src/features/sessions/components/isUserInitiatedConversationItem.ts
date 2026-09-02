export function isUserInitiatedConversationItem(item: {
  type: string;
}): boolean {
  return (
    item.type === "user_message" ||
    item.type === "git_action" ||
    item.type === "skill_button_action"
  );
}
