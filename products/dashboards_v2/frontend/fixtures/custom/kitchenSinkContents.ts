import { lazy } from 'react'

import { defineContentPackage } from '../../panels/custom/customSpec'

const ActivityHeatmap = lazy(() => import('./ActivityHeatmap').then((module) => ({ default: module.ActivityHeatmap })))
const BrowserFilterList = lazy(() => import('./BrowserFilterList').then((module) => ({ default: module.BrowserFilterList })))
const HealthChecklist = lazy(() => import('./HealthChecklist').then((module) => ({ default: module.HealthChecklist })))
const InstrumentationChecklist = lazy(() => import('./InstrumentationChecklist').then((module) => ({ default: module.InstrumentationChecklist })))
const LiveVisitors = lazy(() => import('./LiveVisitors').then((module) => ({ default: module.LiveVisitors })))
const RecommendationDeck = lazy(() => import('./RecommendationDeck').then((module) => ({ default: module.RecommendationDeck })))
const SetupPrompt = lazy(() => import('./SetupPrompt').then((module) => ({ default: module.SetupPrompt })))
const TabbedBreakdown = lazy(() => import('./TabbedBreakdown').then((module) => ({ default: module.TabbedBreakdown })))
const TimeRangeShortcuts = lazy(() => import('./TimeRangeShortcuts').then((module) => ({ default: module.TimeRangeShortcuts })))
const TopIssuesList = lazy(() => import('./TopIssuesList').then((module) => ({ default: module.TopIssuesList })))

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export const kitchenSinkContents = defineContentPackage('kitchen-sink', {
    'setup-prompt': { Component: SetupPrompt, size: { w: 24, h: 5, minW: 8, minH: 3 }, showOnInteractiveOnly: true },
    'browser-filter': { Component: BrowserFilterList, size: { w: 8, h: 8, minW: 6, minH: 6 }, movable: true },
    'time-range-shortcuts': {
        Component: TimeRangeShortcuts,
        size: { w: 24, h: 3, minW: 8, minH: 3 },
        showOnInteractiveOnly: true,
    },
    'health-checklist': { Component: HealthChecklist, size: { w: 8, h: 8, minW: 6, minH: 6 } },
    'top-issues': {
        Component: TopIssuesList,
        size: { w: 12, h: 10, minW: 8, minH: 6 },
        menuActions: (actions) => actions.filter((action) => action.key === 'download-image'),
    },
    'recommendation-deck': {
        Component: RecommendationDeck,
        size: { w: 12, h: 5, minW: 8, minH: 4 },
        showOnInteractiveOnly: true,
    },
    'tabbed-breakdown': {
        Component: TabbedBreakdown,
        size: { w: 12, h: 14, minW: 8, minH: 8 },
        keepMounted: true,
    },
    'activity-heatmap': { Component: ActivityHeatmap, size: { w: 12, h: 14, minW: 8, minH: 8 } },
    'live-visitors': { Component: LiveVisitors, size: { w: 8, h: 8, minW: 6, minH: 6 }, showOnInteractiveOnly: true },
    'instrumentation-checklist': { Component: InstrumentationChecklist, size: { w: 16, h: 8, minW: 8, minH: 4 } },
})
