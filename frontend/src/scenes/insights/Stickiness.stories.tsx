import {
    samplePersonProperties,
    sampleRetentionPeopleResponse,
} from "scenes/insights/__mocks__/insight.mocks";

import { Meta, StoryObj } from "@storybook/react";

import { createInsightStory } from "scenes/insights/__mocks__/createInsightScene";

import { mswDecorator } from "~/mocks/browser";

type Story = StoryObj<{}>;
const meta: Meta = {
    title: "Scenes-App/Insights/Stickiness",
    parameters: {
        layout: "fullscreen",
        testOptions: {
            snapshotBrowsers: ["chromium"],
            viewport: {
                // needs a slightly larger width to push the rendered scene away from breakpoint boundary
                width: 1300,
                height: 720,
            },
        },
        viewMode: "story",
        mockDate: "2022-03-11",
    },
    decorators: [
        mswDecorator({
            get: {
                "/api/environments/:team_id/persons/retention":
                    sampleRetentionPeopleResponse,
                "/api/environments/:team_id/persons/properties":
                    samplePersonProperties,
                "/api/projects/:team_id/groups_types": [],
            },
            post: {
                "/api/projects/:team_id/cohorts/": { id: 1 },
            },
        }),
    ],
};
export default meta;
/* eslint-disable @typescript-eslint/no-var-requires */

// Stickiness

export const Stickiness: Story = createInsightStory(
    require("../../mocks/fixtures/api/projects/team_id/insights/stickiness.json"),
);
Stickiness.parameters = {
    testOptions: { waitForSelector: "[data-attr=trend-line-graph] > canvas" },
};

export const StickinessEdit: Story = createInsightStory(
    require("../../mocks/fixtures/api/projects/team_id/insights/stickiness.json"),
    "edit",
);
StickinessEdit.parameters = {
    testOptions: { waitForSelector: "[data-attr=trend-line-graph] > canvas" },
};

export const StickinessEditViewports: Story = createInsightStory(
    require("../../mocks/fixtures/api/projects/team_id/insights/stickiness.json"),
    "edit",
);
StickinessEditViewports.parameters = {
    testOptions: {
        waitForSelector: "[data-attr=trend-line-graph] > canvas",
        viewportWidths: ["medium", "wide", "superwide"],
    },
};

/* eslint-enable @typescript-eslint/no-var-requires */
