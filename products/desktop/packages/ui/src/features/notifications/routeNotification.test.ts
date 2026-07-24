import type { NotificationTarget } from "@posthog/platform/notifications";
import { describe, expect, it } from "vitest";
import {
  type NotificationChannel,
  routeNotification,
  targetsEqual,
} from "./routeNotification";

const task = (id: string): NotificationTarget => ({ kind: "task", taskId: id });
const canvas = (id: string): NotificationTarget => ({
  kind: "canvas",
  channelId: "chan",
  dashboardId: id,
});

describe("targetsEqual", () => {
  it.each<
    [
      string,
      NotificationTarget | undefined,
      NotificationTarget | undefined,
      boolean,
    ]
  >([
    ["same task", task("t1"), task("t1"), true],
    ["different task", task("t1"), task("t2"), false],
    ["same canvas", canvas("d1"), canvas("d1"), true],
    ["different canvas", canvas("d1"), canvas("d2"), false],
    ["cross-kind", task("t1"), canvas("d1"), false],
    ["one undefined", undefined, task("t1"), false],
    ["both undefined", undefined, undefined, false],
  ])("%s", (_l, a, b, expected) => {
    expect(targetsEqual(a, b)).toBe(expected);
  });
});

describe("routeNotification", () => {
  it.each<
    [string, Parameters<typeof routeNotification>[0], NotificationChannel]
  >([
    [
      "unfocused → native (even when viewing the target)",
      {
        appFocused: false,
        viewingTarget: task("t1"),
        notificationTarget: task("t1"),
      },
      "native",
    ],
    [
      "focused, viewing the exact target → suppress",
      {
        appFocused: true,
        viewingTarget: task("t1"),
        notificationTarget: task("t1"),
      },
      "suppress",
    ],
    [
      "focused, viewing a different target → toast",
      {
        appFocused: true,
        viewingTarget: task("t2"),
        notificationTarget: task("t1"),
      },
      "toast",
    ],
    [
      "focused, viewing nothing relevant → toast",
      {
        appFocused: true,
        viewingTarget: undefined,
        notificationTarget: canvas("d1"),
      },
      "toast",
    ],
    [
      "focused, viewing the same canvas → suppress",
      {
        appFocused: true,
        viewingTarget: canvas("d1"),
        notificationTarget: canvas("d1"),
      },
      "suppress",
    ],
    [
      "focused, targetless notification → toast (can't be 'already viewing it')",
      {
        appFocused: true,
        viewingTarget: task("t1"),
        notificationTarget: undefined,
      },
      "toast",
    ],
  ])("%s", (_l, args, expected) => {
    expect(routeNotification(args)).toBe(expected);
  });
});
