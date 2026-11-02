import { render } from '@testing-library/react'

import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    Describer,
    Description,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { cohortActivityDescriber } from 'scenes/cohorts/activityDescriptions'
import { dashboardActivityDescriber } from 'scenes/dashboard/dashboardActivityDescriber'
import { dataManagementActivityDescriber } from 'scenes/data-management/dataManagementDescribers'
import { notebookActivityDescriber } from 'scenes/notebooks/Notebook/notebookActivityDescriber'
import { surveyActivityDescriber } from 'scenes/surveys/surveyActivityDescriber'
import { teamActivityDescriber } from 'scenes/team-activity/teamActivityDescriber'

import { ActivityScope } from '~/types'

import { actionActivityDescriber } from 'products/actions/frontend/actionActivityDescriber'
import { insightActivityDescriber } from 'products/product_analytics/frontend/insights/activityDescriptions'

describe('humanizeActivity', () => {
    const makeLogItem = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
        activity: 'updated',
        created_at: '2026-06-04T00:00:00Z',
        scope: ActivityScope.FEATURE_FLAG,
        detail: { merge: null, trigger: null, changes: null, name: 'my-flag' },
        ...overrides,
    })

    it.each<{
        scope: ActivityScope
        activity?: string
        describer: Describer
        changes: Partial<ActivityChange>[]
        action: string
        description: string
        preview?: string
    }>([
        {
            scope: ActivityScope.NOTEBOOK,
            describer: notebookActivityDescriber,
            changes: [
                { field: 'content', after: {} },
                { field: 'version', after: 2 },
            ],
            action: 'changed content',
            description: 'A user changed content on Example',
        },
        {
            scope: ActivityScope.TEAM,
            describer: teamActivityDescriber,
            changes: [
                { field: 'session_recording_opt_in', after: true },
                { field: 'effective_membership_level', after: 1 },
                {
                    field: 'feature_flag_policy_config',
                    before: { require_tags: false, blocked_hosts: ['old.example.com'], blocked_ips: [] },
                    after: { require_tags: true, blocked_hosts: ['new.example.com'], blocked_ips: [] },
                },
            ],
            action: 'enabled session recording, enabled required tags on feature flags, added new.example.com to the blocked domains for feature flag requests, and removed old.example.com from the blocked domains for feature flag requests',
            description:
                'A user enabled session recording, enabled required tags on feature flags, added new.example.com to the blocked domains for feature flag requests, and removed old.example.com from the blocked domains for feature flag requests on Example',
        },
        {
            scope: ActivityScope.EVENT_DEFINITION,
            activity: 'changed',
            describer: dataManagementActivityDescriber,
            changes: [
                { field: 'description', after: '' },
                { field: 'verified', after: true },
            ],
            action: 'cleared the description, and marked as verified',
            description: 'A user changed description to "", and marked Example as verified',
            preview: '',
        },
        {
            scope: ActivityScope.ACTION,
            describer: actionActivityDescriber,
            changes: [
                { field: 'description', before: null, after: 'Match sign-ups' },
                { field: 'name', before: 'Original', after: 'Example' },
            ],
            action: 'added the description, and changed the name from "Original" to "Example"',
            description:
                'A user added description "Match sign-ups", and changed the name from "Original" to "Example" on action Example',
            preview: 'Match sign-ups',
        },
    ])('preserves the summary and notification for mapped $scope changes', (testCase) => {
        const logItem = makeLogItem({
            scope: testCase.scope,
            activity: testCase.activity ?? 'updated',
            detail: {
                merge: null,
                trigger: null,
                name: 'Example',
                changes: [...testCase.changes, {}, { field: 'unknown_field' }].map((change) => ({
                    type: testCase.scope,
                    action: 'changed',
                    ...change,
                })),
            },
        })
        const result = testCase.describer(logItem, true)
        const text = (value: Description | undefined): string =>
            (render(<>{value}</>).container.textContent || '').replace(/\s+/g, ' ').trim()

        expect(text(result.description)).toBe(testCase.description)
        expect(text(result.summary?.action)).toBe(testCase.action)
        expect(text(result.summary?.target)).toContain('Example')
        expect(result.summary?.preview).toBe(testCase.preview)
    })

    it.each([
        ['name', 'Original', 'Example', 'renamed "Original" to "Example"'],
        ['derived_name', 'Original', 'Example', 'renamed "Original" to "Example"'],
        ['deleted', false, true, 'deleted the insight'],
        ['deleted', true, false, 'restored the insight'],
        ['short_id', 'old-id', 'new-id', 'changed the short id to "new-id"'],
        ['favorited', false, true, 'favorited the insight'],
        ['favorited', true, false, 'unfavorited the insight'],
    ])('uses the same insight %s headline in the main log and side panel', (field, before, after, expected) => {
        const logItem = makeLogItem({
            scope: ActivityScope.INSIGHT,
            detail: {
                merge: null,
                trigger: null,
                name: 'Example',
                changes: [{ type: ActivityScope.INSIGHT, action: 'changed', field: field as string, before, after }],
            },
        })
        for (const asNotification of [false, true]) {
            const { summary } = insightActivityDescriber(logItem, asNotification)

            expect(render(<>{summary?.action}</>).container.textContent).toBe(expected)
            expect(render(<>{summary?.target}</>).container.textContent).toBe('Example')
        }
    })

    it.each<{ scope: ActivityScope; describer: Describer; activity?: string }>([
        { scope: ActivityScope.DASHBOARD, describer: dashboardActivityDescriber },
        { scope: ActivityScope.INSIGHT, describer: insightActivityDescriber },
        { scope: ActivityScope.COHORT, describer: cohortActivityDescriber },
        { scope: ActivityScope.SURVEY, describer: surveyActivityDescriber },
        { scope: ActivityScope.EVENT_DEFINITION, describer: dataManagementActivityDescriber, activity: 'changed' },
        { scope: ActivityScope.ACTION, describer: actionActivityDescriber },
    ])('uses shared description wording for $scope', ({ scope, describer, activity }) => {
        for (const [before, after, expected] of [
            [null, 'Example description', 'added the description'],
            ['Old description', 'Example description', 'updated the description'],
            ['Old description', '', 'cleared the description'],
        ]) {
            const logItem = makeLogItem({
                scope,
                activity: activity ?? 'updated',
                detail: {
                    name: 'Example',
                    merge: null,
                    trigger: null,
                    changes: [{ type: scope, action: 'changed', field: 'description', before, after }],
                },
            })

            expect(render(<>{describer(logItem).summary?.action}</>).container.textContent).toBe(expected)
        }
    })

    it.each<{ reason: string; changes: Partial<ActivityChange>[]; action: string; description: string }>([
        {
            reason: 'staff_set',
            changes: [
                { field: 'email_sending_tier', before: 2, after: 3 },
                { field: 'email_sending_tier_pinned', before: false, after: true },
            ],
            action: 'Set the workflow email sending tier from 2 to 3 and pinned it there',
            description: 'A user set the workflow email sending tier on Example from 2 to 3 and pinned it there',
        },
        {
            reason: 'clean_and_used',
            changes: [{ field: 'email_sending_tier', before: 1, after: 2 }],
            action: 'Moved the workflow email sending tier from 1 to 2',
            description: 'A user moved the workflow email sending tier on Example from 1 to 2 (reason: clean_and_used)',
        },
        {
            reason: 'staff_set',
            changes: [{ field: 'email_sending_tier_pinned', before: true, after: false }],
            action: 'Unpinned the workflow email sending tier',
            description: 'A user unpinned the workflow email sending tier on Example',
        },
    ])('describes an email sending tier change: $action', ({ reason, changes, action, description }) => {
        const logItem = makeLogItem({
            scope: ActivityScope.TEAM,
            activity: 'email_sending_tier_changed',
            detail: {
                merge: null,
                trigger: null,
                name: 'Example',
                context: { reason },
                changes: changes.map((change) => ({ type: ActivityScope.TEAM, action: 'changed', ...change })),
            },
        })
        const result = teamActivityDescriber(logItem)
        const text = (value: Description | undefined): string =>
            (render(<>{value}</>).container.textContent || '').replace(/\s+/g, ' ').trim()

        expect(text(result.description)).toBe(description)
        expect(text(result.summary?.action)).toBe(action)
    })

    it.each([
        ['minted', 'A user created Developer mode token for a@posthog.com'],
        ['revoked', 'A user revoked Developer mode token for a@posthog.com'],
    ])('describes a %s DevGatewayToken row with the default describer', (activity, expected) => {
        const logItem = makeLogItem({
            scope: ActivityScope.DEV_GATEWAY_TOKEN,
            activity,
            detail: { merge: null, trigger: null, changes: null, name: 'Developer mode token for a@posthog.com' },
        })
        const { description } = defaultDescriber(logItem)

        expect(
            render(<>{description}</>)
                .container.textContent?.replace(/\s+/g, ' ')
                .trim()
        ).toBe(expected)
    })

    describe('userNameForLogItem', () => {
        it.each([
            [
                'uses the full name when set',
                { user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' } },
                'Ada Lovelace',
            ],
            [
                'falls back to email when the name is blank',
                { user: { first_name: '', last_name: '', email: 'ada@posthog.com' } },
                'ada@posthog.com',
            ],
            [
                'falls back to the placeholder when name and email are both blank',
                { user: { first_name: '', last_name: '', email: '' } },
                'A user',
            ],
            ['falls back to the placeholder when there is no user', {}, 'A user'],
            ['renders system activity as PostHog', { is_system: true }, 'PostHog'],
            [
                'falls back to email for impersonated actors with a blank name',
                { was_impersonated: true, user: { first_name: '', last_name: '', email: 'ada@posthog.com' } },
                'PostHog Support (as ada@posthog.com)',
            ],
        ])('%s', (_name, overrides: Partial<ActivityLogItem>, expected: string) => {
            expect(userNameForLogItem(makeLogItem(overrides))).toEqual(expected)
        })
    })

    describe('ActivityLogUserName', () => {
        // Base UI marks the element it merges the tooltip trigger onto. Opening the popup is not
        // reliable in jsdom because of the hover delay, so assert on the trigger instead.
        const renderName = (overrides: Partial<ActivityLogItem>): HTMLElement => {
            const { container } = render(<ActivityLogUserName logItem={makeLogItem(overrides)} />)
            const element = container.querySelector('strong')
            if (!element) {
                throw new Error('ActivityLogUserName rendered no name element')
            }
            return element
        }

        it.each([
            [
                'offers the email when the name does not already show it',
                { user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' } },
                true,
            ],
            [
                'stays plain when the visible name is already the email',
                { user: { first_name: '', last_name: '', email: 'ada@posthog.com' } },
                false,
            ],
            ['stays plain when the actor is the system', { is_system: true }, false],
            [
                'stays plain when a staff member was impersonating the actor',
                {
                    was_impersonated: true,
                    user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' },
                },
                false,
            ],
            ['stays plain when there is no user', {}, false],
        ])('%s', (_name, overrides: Partial<ActivityLogItem>, expectTooltip: boolean) => {
            const element = renderName(overrides)
            expect(element.hasAttribute('data-base-ui-tooltip-trigger')).toBe(expectTooltip)
            // The only visual cue that the name is hoverable.
            expect(element.classList.contains('cursor-help')).toBe(expectTooltip)
            // Dropping this on either branch sends every actor name into session replay.
            expect(element.classList.contains('ph-no-capture')).toBe(true)
        })
    })
})
