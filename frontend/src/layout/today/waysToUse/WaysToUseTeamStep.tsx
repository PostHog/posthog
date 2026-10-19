import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconDashboard, IconFlask, IconMessage, IconNotebook, IconToggle, IconTrends } from '@posthog/icons'
import { Button, Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { isString } from 'lib/utils/guards'
import { EXPLORE_ITEMS } from 'scenes/project-homepage/today/todayExploreItems'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import type { TodayRowIcon } from 'scenes/project-homepage/today/todayRowIcons'
import { urls } from 'scenes/urls'
import { brandingForProduct } from 'scenes/welcome/productBranding'

import { WaysToUseTeamWorkItem, teamWorkLabel, teammatesSummary } from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'
import { WaysToUseTeammates } from './WaysToUseTeammates'

const SCOPE_ICONS: Record<string, TodayRowIcon> = {
    Dashboard: { color: 'var(--color-product-product-analytics-light)', glyph: <IconDashboard /> },
    Insight: { color: 'var(--color-product-product-analytics-light)', glyph: <IconTrends /> },
    FeatureFlag: { color: 'var(--color-product-feature-flags-light)', glyph: <IconToggle /> },
    Experiment: { color: 'var(--color-product-experiments-light)', glyph: <IconFlask /> },
    Survey: { color: 'var(--color-product-surveys-light)', glyph: <IconMessage /> },
    Notebook: { color: 'var(--color-product-product-analytics-light)', glyph: <IconNotebook /> },
}

function teamWorkIcon(item: WaysToUseTeamWorkItem): TodayRowIcon {
    return SCOPE_ICONS[item.type.split('.')[0]] ?? SCOPE_ICONS.Insight
}

function productIcon(productKey: string): TodayRowIcon {
    const { Icon } = brandingForProduct(productKey)
    return { color: `var(--color-product-${productKey.replace(/_/g, '-')}-light)`, glyph: <Icon /> }
}

export function WaysToUseTeamStep(): JSX.Element {
    const { teamWork, productsInUse, teamMembers } = useValues(waysToUseLogic)
    const { closeWaysToUse, trackWaysToUseClick } = useActions(waysToUseLogic)
    const workId = useId()
    const productsId = useId()
    const teammatesId = useId()
    const workSection = teamWork.length > 0 && (
        <section aria-labelledby={workId} className="flex min-w-0 flex-col gap-2">
            <h3 id={workId} className="TodayHome__heading">
                Your team's work
            </h3>
            <div className="-mx-3 flex flex-col">
                {teamWork.map((item) => (
                    <TodayRow
                        key={item.url}
                        tone="neutral"
                        icon={teamWorkIcon(item)}
                        title={item.name}
                        label={teamWorkLabel(item.type)}
                        facts={[item.detail]}
                        to={item.url}
                        onOpen={() => closeWaysToUse('surface_link', 'team_work')}
                        dataAttr="today-ways-to-use-team-work"
                    />
                ))}
            </div>
        </section>
    )
    const productsSection = productsInUse.length > 0 && (
        <section aria-labelledby={productsId} className="flex min-w-0 flex-col gap-2">
            <h3 id={productsId} className="TodayHome__heading">
                Products your team uses
            </h3>
            <div className="-mx-3 flex flex-col">
                {productsInUse.map((productKey) => {
                    const { label, docsHref } = brandingForProduct(productKey)
                    return (
                        <TodayRow
                            key={productKey}
                            tone="neutral"
                            icon={productIcon(productKey)}
                            title={label}
                            label="Docs"
                            facts={[EXPLORE_ITEMS.find((item) => item.product === productKey)?.description].filter(
                                isString
                            )}
                            to={docsHref}
                            onOpen={() => trackWaysToUseClick('product_docs')}
                            dataAttr="today-ways-to-use-product-docs"
                        />
                    )
                })}
            </div>
        </section>
    )
    const teammatesSection = teamMembers.length > 0 && (
        <section aria-labelledby={teammatesId} className="flex min-w-0 flex-col gap-3">
            <h3 id={teammatesId} className="TodayHome__heading">
                Your teammates
            </h3>
            <WaysToUseTeammates members={teamMembers} />
            <Text size="xs" variant="muted" className="m-0 text-pretty">
                {teammatesSummary(teamMembers)}
            </Text>
            <Button
                size="sm"
                variant="outline"
                nativeButton={false}
                role="link"
                className="w-fit"
                render={
                    <LinkPrimitive
                        to={urls.settings('organization-members')}
                        onClick={() => closeWaysToUse('surface_link', 'members')}
                    />
                }
                data-attr="today-ways-to-use-members"
            >
                See everyone
            </Button>
        </section>
    )
    const productsWithWork = teamWork.length < productsInUse.length + 2
    const hasMainColumn = !!workSection || (productsWithWork && !!productsSection)
    const hasSideColumn = !!teammatesSection || (!productsWithWork && !!productsSection)

    return (
        <div className="@container">
            <div
                className={cn(
                    'grid grid-cols-1 gap-x-10 gap-y-8',
                    hasMainColumn && hasSideColumn && '@3xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'
                )}
            >
                {hasMainColumn && (
                    <div className="flex min-w-0 flex-col gap-8">
                        {workSection}
                        {productsWithWork && productsSection}
                    </div>
                )}
                {hasSideColumn && (
                    <div className="flex min-w-0 flex-col gap-8">
                        {!productsWithWork && productsSection}
                        {teammatesSection}
                    </div>
                )}
            </div>
        </div>
    )
}
