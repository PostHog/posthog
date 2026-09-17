import type {
  BackupReview,
  BackupScope,
} from "@posthog/core/settings/settingsBackup";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  SettingsBackupView,
  type SettingsBackupViewProps,
} from "./SettingsBackup";

describe("SettingsBackupView", () => {
  const review: BackupReview = {
    backup: {
      format: "posthog-desktop-settings",
      formatVersion: 1,
      appVersion: "1.3.0",
      exportedAt: "2026-01-12T12:00:00.000Z",
      settings: {},
      sounds: [],
    },
    settings: { theme: "dark", completionVolume: 75 },
    sounds: [],
    warnings: [
      { key: "completionVolume", reason: "changed" },
      { key: "theme", reason: "changed" },
      { key: "removedPreference", reason: "unknown" },
      { key: "Completion sound", reason: "selection" },
      { key: "Sound 3", reason: "sound" },
    ],
    currentVersion: "1.3.0",
  };
  const props: SettingsBackupViewProps = {
    soundCount: 4,
    scope: "all",
    onScopeChange: () => {},
    busy: null,
    review,
    error: null,
    message: null,
    onExport: () => {},
    onOpen: () => {},
    onImport: () => {},
    onCancel: () => {},
  };

  it.each<[BackupScope, string[]]>([
    [
      "all",
      [
        "Completion volume",
        "Theme",
        "Removed preference",
        "Completion sound",
        "Sound 3",
      ],
    ],
    ["sounds", ["Completion volume", "Completion sound", "Sound 3"]],
  ])("warns only about what the %s import reads", (scope, expected) => {
    render(<SettingsBackupView {...props} scope={scope} />);

    expect(
      screen
        .getAllByRole("listitem")
        .map((item) => item.firstElementChild?.textContent),
    ).toEqual(expected);
    expect(screen.getByText(/compatibility warning/).textContent).toBe(
      `${expected.length} compatibility warnings`,
    );
  });
});
