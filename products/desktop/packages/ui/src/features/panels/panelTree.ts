import * as core from "@posthog/core/panels/panelTree";
import type { PanelNode, Tab } from "./panelTypes";

export const removeTabFromPanel = core.removeTabFromPanel as (
  node: PanelNode,
  tabId: string,
) => PanelNode;

export const addTabToPanel = core.addTabToPanel as (
  node: PanelNode,
  tab: Tab,
) => PanelNode;

export const setActiveTabInPanel = core.setActiveTabInPanel as (
  node: PanelNode,
  tabId: string,
) => PanelNode;

export const findTabInPanel = core.findTabInPanel as (
  panel: Extract<PanelNode, { type: "leaf" }>,
  tabId: string,
) => Tab | undefined;

export const findTabInTree = core.findTabInTree as (
  node: PanelNode,
  tabId: string,
) => { panelId: string; tab: Tab } | null;

export const updateTreeNode = core.updateTreeNode as (
  node: PanelNode,
  targetId: string,
  updateFn: (node: PanelNode) => PanelNode,
) => PanelNode;

export const cleanupNode = core.cleanupNode as (
  node: PanelNode,
) => PanelNode | null;

export const mergeTreeContent = core.mergeTreeContent as (
  existingTree: PanelNode,
  newTree: PanelNode,
) => PanelNode;

export const isLeaf = core.isLeaf as (
  node: PanelNode | null,
) => node is Extract<PanelNode, { type: "leaf" }>;

export const isGroup = core.isGroup as (
  node: PanelNode | null,
) => node is Extract<PanelNode, { type: "group" }>;
