import { cloneElement, type ReactElement } from "react";
import { StyleSheet, Text, type TextProps, type TextStyle } from "react-native";
import {
  FONT_SCALE_BY_PREFERENCE,
  usePreferencesStore,
} from "@/features/preferences/stores/preferencesStore";

// Apply Open Runde as the default fontFamily for every <Text>, including those
// imported directly from react-native, and scale every explicit fontSize by the
// user's chosen font-size preference. User-provided styles (e.g. font-mono via
// NativeWind className) appear later in the style array and override the
// default; the scaled fontSize is appended last so it always wins.
type PatchableText = {
  render: (...args: unknown[]) => ReactElement<TextProps>;
  __posthogPatched?: boolean;
};
const TextRef = Text as unknown as PatchableText;

const FONT_FAMILY_STYLE = { fontFamily: "Open Runde" } as const;

if (!TextRef.__posthogPatched) {
  const baseRender = TextRef.render;
  TextRef.render = function patchedRender(...args) {
    const element = baseRender.apply(this, args);

    // Read the scale imperatively (this runs outside React, so no hooks). The
    // value is persisted and read on every render, so changing it in Settings
    // takes effect as each screen re-renders.
    const scale =
      FONT_SCALE_BY_PREFERENCE[usePreferencesStore.getState().fontSize];

    if (scale === 1) {
      return cloneElement(element, {
        style: [FONT_FAMILY_STYLE, element.props.style],
      });
    }

    // Only scale a fontSize that is explicitly set on this node. Nodes without
    // one inherit their (already-scaled) parent in React Native, so injecting a
    // default here would break inheritance for nested <Text>.
    const flattened = StyleSheet.flatten(element.props.style) as
      | TextStyle
      | undefined;
    const scaledStyle =
      flattened && typeof flattened.fontSize === "number"
        ? { fontSize: flattened.fontSize * scale }
        : null;

    return cloneElement(element, {
      style: [FONT_FAMILY_STYLE, element.props.style, scaledStyle],
    });
  };
  TextRef.__posthogPatched = true;
}
