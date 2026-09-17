export function goalValueSuffix(goalName: string): string {
  return /%|percent|conversion/i.test(goalName) ? "%" : "";
}
