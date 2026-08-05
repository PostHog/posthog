import "./mocks/electron-trpc";
import { Theme } from "@radix-ui/themes";
import "@radix-ui/themes/styles.css";
import type { Preview } from "@storybook/react-vite";
import MockDate from "mockdate";
import "../../../packages/ui/src/styles/globals.css";
import { withAppProviders } from "./withAppProviders";

function inStorybookTestRunner(): boolean {
  return navigator.userAgent.includes("StorybookTestRunner");
}

function seededMathRandom(): void {
  let state = 0x9e3779b9;
  Math.random = () => {
    state = Math.imul(state ^ (state >>> 15), state | 1);
    state ^= state + Math.imul(state ^ (state >>> 7), state | 61);
    return ((state ^ (state >>> 14)) >>> 0) / 4294967296;
  };
}

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    backgrounds: {
      options: {
        dark: { name: "dark", value: "#111113" },
        light: { name: "light", value: "#ffffff" },
      },
    },
  },

  decorators: [
    withAppProviders,
    (Story, context) => {
      const isDark = context.globals.theme !== "light";
      // Mirror the app's ThemeWrapper (packages/ui/src/primitives/ThemeWrapper.tsx)
      // so stories render with the shipped radius and accent colors.
      return (
        <Theme
          appearance={isDark ? "dark" : "light"}
          accentColor={isDark ? "yellow" : "orange"}
          grayColor="slate"
          panelBackground="solid"
          radius="medium"
          scaling="105%"
        >
          <Story />
          {/* Match ThemeWrapper so portaled Quill components inherit the story's active theme. */}
          <div id="portal-container" />
        </Theme>
      );
    },
    // Last in the array = outermost, so it runs before every story render.
    // Visual regression snapshots need identical pixels on every render:
    // freeze the clock (elapsed-time counters, rendered timestamps) and
    // re-seed Math.random (random status verbs), including on the re-renders
    // the test runner triggers for theme flips and retries. This must live in
    // a decorator, not module scope: the test runner appends its UA marker
    // via an injected script AFTER the page (and this module) loads, so a
    // module-scope inStorybookTestRunner() check reads false. Story-module
    // fixtures evaluated at import time still see the real clock — use fixed
    // dates there.
    (Story) => {
      if (inStorybookTestRunner()) {
        MockDate.set("2026-07-01T10:30:00Z");
        seededMathRandom();
      }
      return <Story />;
    },
  ],

  globalTypes: {
    theme: {
      description: "Theme",
      defaultValue: "dark",
      toolbar: {
        title: "Theme",
        icon: "circlehollow",
        items: ["dark", "light"],
        dynamicTitle: true,
      },
    },
  },

  initialGlobals: {
    backgrounds: {
      value: "dark",
    },
  },
};

export default preview;
