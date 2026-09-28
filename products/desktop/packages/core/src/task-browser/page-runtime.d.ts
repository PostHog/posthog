export type PageKit = { readonly __pageKit: unique symbol };

export type ElementBox =
  | {
      x: number;
      y: number;
      width: number;
      height: number;
      left: number;
      top: number;
    }
  | { problem: "hidden" | "covered" };

export type ElementSensitivity = {
  typesPassword: boolean;
  password: boolean;
  payment: boolean;
  submitsData: boolean;
  destructive: boolean;
  label: string;
};

export type FocusedForm = {
  password: boolean;
  payment: boolean;
  filled: boolean;
};

export function pageKit(): PageKit;
export function snapshot(kit: PageKit, args: { maxChars: number }): string;
export function rect(
  kit: PageKit,
  args: { ref: string; forClick: boolean },
): ElementBox | null;
export function focus(
  kit: PageKit,
  args: { ref: string; clear: boolean },
): boolean;
export function findText(kit: PageKit, args: { text: string }): string | null;
export function sensitivity(
  kit: PageKit,
  args: { ref: string },
): ElementSensitivity | null;
export function focusedForm(kit: PageKit): FocusedForm | null;
