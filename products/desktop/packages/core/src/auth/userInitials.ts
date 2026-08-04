interface UserLike {
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
}

function firstLetter(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = value.match(/\p{L}/u);
  return match ? match[0] : null;
}

export function getUserInitials(user: UserLike | null | undefined): string {
  const first = firstLetter(user?.first_name);
  const last = firstLetter(user?.last_name);
  if (first && last) {
    return `${first}${last}`.toUpperCase();
  }
  if (first) {
    return first.toUpperCase();
  }
  if (last) {
    return last.toUpperCase();
  }
  const emailLocal = user?.email?.split("@")[0];
  const emailLetters = emailLocal?.match(/\p{L}/gu)?.slice(0, 2).join("");
  if (emailLetters) {
    return emailLetters.toUpperCase();
  }
  return "U";
}
