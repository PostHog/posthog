import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { ShellLocation, ShellScope } from '../shellNavigation'
import { ShellFrame } from './ShellFrame'

const NOWHERE: ShellLocation = { tab: null, scope: null }

function renderFrame({
    location = NOWHERE,
    linkParams = {},
    todayRailNav = false,
    onScopeChange = () => {},
}: {
    location?: ShellLocation
    linkParams?: Record<string, unknown>
    todayRailNav?: boolean
    onScopeChange?: (scope: ShellScope) => void
} = {}): HTMLElement {
    initKeaTests()
    return render(
        <ShellFrame
            location={location}
            linkParams={linkParams}
            todayRailNav={todayRailNav}
            onScopeChange={onScopeChange}
        >
            <div data-attr="body" />
        </ShellFrame>
    ).container
}

function activeTabs(container: HTMLElement): (string | null | undefined)[] {
    return Array.from(container.querySelectorAll('[role="tab"][aria-selected="true"]')).map((tab) =>
        tab.querySelector('[data-attr^="ai-observability-tab-"]')?.getAttribute('data-attr')
    )
}

function scopeOptions(container: HTMLElement): Element[] {
    return Array.from(container.querySelectorAll('[data-attr^="ai-observability-scope-"]'))
}

function href(container: HTMLElement, dataAttr: string): string {
    const element = container.querySelector(`[data-attr="${dataAttr}"]`)
    const anchor = element?.closest('a') ?? element?.querySelector('a')
    return anchor?.getAttribute('href') ?? ''
}

describe('ShellFrame', () => {
    afterEach(cleanup)

    it.each<[ShellLocation, string]>([
        [{ tab: 'home', scope: null }, 'ai-observability-tab-home'],
        [{ tab: 'activity', scope: 'traces' }, 'ai-observability-tab-activity'],
        [{ tab: 'diagnostics', scope: 'tools' }, 'ai-observability-tab-diagnostics'],
        [{ tab: 'people', scope: null }, 'ai-observability-tab-people'],
    ])('marks the tab of %j active', (location, dataAttr) => {
        expect(activeTabs(renderFrame({ location }))).toEqual([dataAttr])
    })

    it('marks no tab active and shows no switch on a path with no tab', () => {
        const container = renderFrame()

        expect(activeTabs(container)).toEqual([])
        expect(scopeOptions(container)).toEqual([])
        expect(container.querySelector('[data-attr="body"]')).not.toBeNull()
    })

    it.each<[ShellLocation, string[], string | null]>([
        [
            { tab: 'activity', scope: 'sessions' },
            ['ai-observability-scope-sessions', 'ai-observability-scope-traces'],
            'ai-observability-scope-sessions',
        ],
        [
            { tab: 'diagnostics', scope: 'tools' },
            ['ai-observability-scope-errors', 'ai-observability-scope-tools'],
            'ai-observability-scope-tools',
        ],
        [{ tab: 'home', scope: null }, [], null],
    ])('shows the switch of %j with the current scope active', (location, options, active) => {
        const shown = scopeOptions(renderFrame({ location }))

        expect(shown.map((option) => option.getAttribute('data-attr'))).toEqual(options)
        expect(
            shown
                .filter((option) => option.closest('.LemonSegmentedButton__option--selected'))
                .map((option) => option.getAttribute('data-attr'))
        ).toEqual(active ? [active] : [])
    })

    it('reports the scope a person picks on the switch', () => {
        const picked: string[] = []
        const container = renderFrame({
            location: { tab: 'activity', scope: 'traces' },
            onScopeChange: (scope) => picked.push(`${scope.id} ${scope.path}`),
        })

        const sessions = container.querySelector('[data-attr="ai-observability-scope-sessions"]')
        if (!sessions) {
            throw new Error('No sessions option')
        }
        fireEvent.click(sessions)

        expect(picked).toEqual([`sessions ${urls.aiObservabilitySessions()}`])
    })

    it('carries the link params on the tab links', () => {
        const container = renderFrame({
            location: { tab: 'activity', scope: 'traces' },
            linkParams: {
                date_from: '-7d',
                filters: [{ key: '$ai_model', value: ['gpt-4'], operator: 'exact', type: 'event' }],
            },
        })

        const link = href(container, 'ai-observability-tab-diagnostics')
        expect(link).toContain(`${urls.aiObservabilityErrors()}?`)
        expect(link).toContain('date_from=-7d')
        expect(decodeURIComponent(link)).toContain('"key":"$ai_model"')
    })

    // The tab bar measures its selected tab to place the underline, and jsdom lays nothing out.
    it('clears the underline when the route moves from a tab to a page with no tab', () => {
        const offsetWidth = jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(120)
        initKeaTests()
        const frame = (location: ShellLocation): JSX.Element => (
            <ShellFrame location={location} linkParams={{}} todayRailNav={false} onScopeChange={() => {}}>
                <div />
            </ShellFrame>
        )
        const view = render(frame({ tab: 'home', scope: null }))
        const underlineWidth = (): string | undefined =>
            view.container
                .querySelector<HTMLElement>('[data-attr="ai-observability-tabs"]')
                ?.style.getPropertyValue('--lemon-tabs-slider-width')
        expect(underlineWidth()).toBe('120px')

        view.rerender(frame(NOWHERE))

        expect(underlineWidth()).toBe('0px')
        offsetWidth.mockRestore()
    })

    it.each([true, false])('links Documentation to the scope docs page with todayRailNav %s', (todayRailNav) => {
        renderFrame({ location: { tab: 'activity', scope: 'sessions' }, todayRailNav })

        expect(screen.getByText('Documentation').closest('a')?.getAttribute('href')).toBe(
            'https://posthog.com/docs/ai-observability/sessions'
        )
    })
})
