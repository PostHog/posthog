import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { WidgetCardHeader, type DashboardWidgetTopHeadingProps } from './WidgetCardHeader'

describe('WidgetCardHeader', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders dashboard_tile layout with top heading and title', () => {
        const { container } = render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                topHeading={<span>Error tracking • Last 7 days</span>}
                moreButtonOverlay={<div>Menu</div>}
            />
        )

        expect(screen.getByText('Error tracking • Last 7 days')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="widget-card-title"]')).toHaveTextContent('Top issues')
        expect(container.querySelector('.CardMeta--compact')).toBeTruthy()
        expect(container.querySelector('.CardMeta__divider')).toBeTruthy()
    })

    it('derives top heading from catalog header meta', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                widgetTypeLabel="Error tracking"
                config={{ dateRange: { date_from: '-7d' } }}
                headerMeta={{ showWidgetType: true, showDateRange: true }}
            />
        )

        expect(screen.getByText('Error tracking')).toBeInTheDocument()
        expect(screen.getByText('Last 7 days')).toBeInTheDocument()
    })

    it('renders an injected per-widget top heading in place of the default date range', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Recent recordings"
                widgetTypeLabel="Session replay"
                config={{ dateRange: { date_from: '-14d' }, savedFilterId: 'abc123' }}
                headerMeta={{ showWidgetType: true, showDateRange: true }}
                TopHeading={({ widgetTypeLabel }: DashboardWidgetTopHeadingProps) => (
                    <span>{widgetTypeLabel} • My saved filter</span>
                )}
            />
        )

        expect(screen.getByText('Session replay • My saved filter')).toBeInTheDocument()
        expect(screen.queryByText('Last 14 days')).not.toBeInTheDocument()
    })

    it('derives date-only top heading when widget type is hidden', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                widgetTypeLabel="Error tracking"
                config={{ dateRange: { date_from: '-30d' } }}
                headerMeta={{ showWidgetType: false, showDateRange: true }}
            />
        )

        expect(screen.queryByText('Error tracking')).not.toBeInTheDocument()
        expect(screen.getByText('Last 30 days')).toBeInTheDocument()
    })

    it('omits top heading when catalog meta hides both rows', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                widgetTypeLabel="Error tracking"
                config={{}}
                headerMeta={{ showWidgetType: false, showDateRange: false }}
            />
        )

        expect(screen.queryByText('Error tracking')).not.toBeInTheDocument()
        expect(screen.queryByText('Last 7 days')).not.toBeInTheDocument()
    })

    it('links the title when titleHref is set', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                titleHref="/error_tracking"
                topHeading={<span>Error tracking • Last 7 days</span>}
            />
        )

        expect(screen.getByText('Top issues').closest('a')).toHaveAttribute('href', '/error_tracking')
    })

    it('does not link the title in dashboard edit mode even when titleHref is set', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                titleHref="/error_tracking"
                showEditingControls
                isDashboardEditMode
            />
        )

        expect(screen.getByText('Top issues').closest('a')).toBeNull()
        expect(screen.getByText('Top issues')).toBeInTheDocument()
    })

    it('links the title in view mode when editing controls are shown', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                titleHref="/error_tracking"
                showEditingControls
            />
        )

        expect(screen.getByText('Top issues').closest('a')).toHaveAttribute('href', '/error_tracking')
    })

    it('forwards the hover refresh control into the dashboard_tile header', () => {
        const { container } = render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                topHeading={<span>Error tracking • Last 7 days</span>}
                moreButtonOverlay={<div>Menu</div>}
                refreshControl={<button className="CardMeta__refresh" data-attr="dashboard-widget-refresh" />}
            />
        )

        expect(container.querySelector('[data-attr="dashboard-widget-refresh"]')).toBeTruthy()
        expect(container.querySelector('.CardMeta__controls .CardMeta__refresh')).toBeTruthy()
    })

    it('renders simple layout without inline refresh', () => {
        const { container } = render(<WidgetCardHeader layout="simple" title="My widget" showEditingControls={false} />)

        expect(container.querySelector('.WidgetCard__header h3')).toHaveTextContent('My widget')
        expect(screen.queryByText('Refresh')).not.toBeInTheDocument()
        expect(container.querySelector('.CardMeta--compact')).toBeNull()
    })

    it('renders description in view mode when set', () => {
        render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                description="Track the most common errors"
                showEditingControls={false}
            />
        )

        expect(screen.getByText('Track the most common errors')).toBeInTheDocument()
    })

    it('does not render description in view mode when empty', () => {
        const { container } = render(
            <WidgetCardHeader layout="dashboard_tile" title="Top issues" showEditingControls={false} />
        )

        expect(container.querySelector('.CardMeta__description')).toBeNull()
    })

    it('hides description when showDescription is false', () => {
        const { container } = render(
            <WidgetCardHeader
                layout="dashboard_tile"
                title="Top issues"
                description="Track the most common errors"
                showDescription={false}
                showEditingControls
            />
        )

        expect(container.querySelector('.CardMeta__description')).toBeNull()
    })

    it('renders default title without italic when custom title is empty', () => {
        const { container } = render(
            <WidgetCardHeader layout="dashboard_tile" title="" defaultTitle="Top issues" showEditingControls={false} />
        )

        expect(container.querySelector('[data-attr="widget-card-title"]')).toHaveTextContent('Top issues')
        expect(container.querySelector('i')).toBeNull()
    })

    it('renders read-only default title in edit mode', () => {
        const { container } = render(
            <WidgetCardHeader layout="dashboard_tile" title="" defaultTitle="Top issues" showEditingControls />
        )

        expect(container.querySelector('[data-attr="widget-card-title"]')).toHaveTextContent('Top issues')
        expect(container.querySelector('.EditableField')).toBeNull()
        expect(container.querySelector('i')).toBeNull()
    })
})
