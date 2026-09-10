import { toast } from "../../primitives/toast";
import type { FocusSagaResult } from "./focusStore";

export function showFocusSuccessToast(
  branchName: string,
  result: FocusSagaResult,
): void {
  const showStashMessage = !!result.session?.mainStashRef && !result.wasSwap;
  toast.success(`Now editing ${branchName}`, {
    description: showStashMessage
      ? "Your local changes were stashed and will be restored when you return."
      : undefined,
  });
}
