import type { IconProps } from "@phosphor-icons/react";
import { FileTextIcon } from "@phosphor-icons/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentType, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { DetailSection } from "./DetailSection";
import { RightColumnSection } from "./RightColumnSection";

interface SectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

const sections: ReadonlyArray<[string, ComponentType<SectionProps>]> = [
  ["DetailSection", DetailSection],
  ["RightColumnSection", RightColumnSection],
];

describe("collapsible inbox detail sections", () => {
  it.each(sections)(
    "%s starts expanded, toggles its body, and leaves the right slot interactive",
    async (_name, Section): Promise<void> => {
      const user = userEvent.setup();
      const onRightSlotClick = vi.fn();

      render(
        <Section
          Icon={FileTextIcon}
          title="Section title"
          rightSlot={
            <button type="button" onClick={onRightSlotClick}>
              Section action
            </button>
          }
        >
          <div>Section body</div>
        </Section>,
      );

      const toggle = screen.getByRole("button", { name: "Section title" });
      const body = screen.getByText("Section body");
      const controlledRegion = document.getElementById(
        toggle.getAttribute("aria-controls") ?? "",
      );

      expect(toggle).toHaveAttribute("aria-expanded", "true");
      expect(controlledRegion).toContainElement(body);
      expect(body).toBeVisible();

      await user.click(screen.getByRole("button", { name: "Section action" }));

      expect(onRightSlotClick).toHaveBeenCalledOnce();
      expect(toggle).toHaveAttribute("aria-expanded", "true");
      expect(body).toBeVisible();

      await user.click(toggle);

      expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByText("Section body")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Section action" }),
      ).toBeVisible();

      await user.click(toggle);

      expect(toggle).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByText("Section body")).toBeVisible();
    },
  );

  it.each(sections)(
    "%s supports starting collapsed",
    (_name, Section): void => {
      render(
        <Section Icon={FileTextIcon} title="Section title" defaultOpen={false}>
          <div>Section body</div>
        </Section>,
      );

      expect(
        screen.getByRole("button", { name: "Section title" }),
      ).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByText("Section body")).not.toBeInTheDocument();
    },
  );
});
