import { cleanup, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { type ExperimentRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { VariantActionsMenu } from './VariantActionsMenu'

const experiment = { id: 7 } as Experiment

const metric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.MEAN,
    uuid: 'metric-mean',
    source: { kind: NodeKind.EventsNode, event: 'purchase' },
} as unknown as ExperimentMetric

const selectableModes: ExperimentRecordingModes = {
    metricSelectable: true,
    unselectableReason: null,
    unselectableCode: null,
    defaultMode: 'fired_all',
    menuItems: [
        { mode: 'fired_all', label: 'Fired purchase', tooltip: '', disabledReason: null },
        { mode: 'no_metric_activity', label: "Didn't fire purchase", tooltip: '', disabledReason: null },
    ],
}

const droppedMetricModes: ExperimentRecordingModes = {
    metricSelectable: false,
    unselectableReason: 'Retention metrics measure a return visit in a later session.',
    unselectableCode: 'retention',
    defaultMode: null,
    menuItems: [
        {
            mode: 'fired_all',
            label: 'Fired purchase',
            tooltip: '',
            disabledReason: 'Retention metrics measure a return visit in a later session.',
        },
        {
            mode: 'no_metric_activity',
            label: "Didn't fire purchase",
            tooltip: '',
            disabledReason: 'Retention metrics measure a return visit in a later session.',
        },
    ],
}

const linkParams = (element: Element | null): Record<string, string> =>
    Object.fromEntries(new URLSearchParams(element?.getAttribute('href')?.split('?')[1] ?? ''))

const item = (dataAttr: string): Element | null => document.querySelector(`[data-attr="${dataAttr}"]`)

const openMenu = async (modes: ExperimentRecordingModes, hogql?: string): Promise<void> => {
    const { container } = render(
        <VariantActionsMenu
            experiment={experiment}
            metric={metric}
            variantKey="test"
            isBaseline={false}
            modes={modes}
            hogql={hogql}
        />
    )
    await userEvent.click(container.querySelector('[data-attr="experiment-variant-actions"]')!)
}

const openRecordings = async (modes: ExperimentRecordingModes): Promise<void> => {
    await openMenu(modes, 'SELECT 1')
    await userEvent.click(item('experiment-variant-menu-recordings')!)
}

describe('VariantActionsMenu', () => {
    beforeEach(() => {
        initKeaTests(false)
        router.mount()
    })

    afterEach(() => {
        cleanup()
        document.body.innerHTML = ''
    })

    it('links each recordings item to the variant, filtered to the metric', async () => {
        await openRecordings(selectableModes)

        expect(linkParams(item('experiment-variant-menu-recordings-fired_all'))).toEqual({
            tab: 'recordings',
            variant: 'test',
            metric_uuid: 'metric-mean',
            metric_filter: 'fired_all',
            entry: 'results_menu',
        })
        expect(linkParams(item('experiment-variant-menu-recordings-all'))).toEqual({
            tab: 'recordings',
            variant: 'test',
            entry: 'results_menu',
        })
    })

    it('refuses the metric filters for a metric the tab would drop, and still offers every recording', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        await openRecordings(droppedMetricModes)

        expect(item('experiment-variant-menu-recordings-fired_all')?.getAttribute('aria-disabled')).toEqual('true')
        expect(item('experiment-variant-menu-recordings-no_metric_activity')?.getAttribute('aria-disabled')).toEqual(
            'true'
        )
        expect(linkParams(item('experiment-variant-menu-recordings-all'))).toEqual({
            tab: 'recordings',
            variant: 'test',
            entry: 'results_menu',
        })

        await userEvent.click(item('experiment-variant-menu-recordings-all')!)
        expect(captureSpy).toHaveBeenLastCalledWith(
            'viewed recordings from experiment',
            expect.objectContaining({ trigger: 'menu', surface: 'metrics_table', metric_unavailable_reason: null })
        )
    })

    it('opens the metric query in the SQL editor', async () => {
        await openMenu(selectableModes, 'SELECT count() FROM events')

        const href = item('experiment-variant-menu-open-sql')?.getAttribute('href') ?? ''
        expect(href).toContain('/sql')
        expect(new URLSearchParams(href.split('?')[1]).get('open_query')).toEqual('SELECT count() FROM events')
    })

    it('refuses the SQL actions while the metric has no query', async () => {
        await openMenu(selectableModes)

        expect(item('experiment-variant-menu-copy-sql')?.getAttribute('aria-disabled')).toEqual('true')
        expect(item('experiment-variant-menu-open-sql')?.getAttribute('aria-disabled')).toEqual('true')
    })
})
