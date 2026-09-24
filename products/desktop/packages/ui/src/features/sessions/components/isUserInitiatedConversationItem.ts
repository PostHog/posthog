export function isUserInitiatedConversationItem(item: {
  type: string;
  deliveryFailed?: boolean;
}): boolean {
  return (
    (item.type === "user_message" && !item.deliveryFailed) ||
    item.type === "git_action" ||
    item.type === "skill_button_action"
  );
}
