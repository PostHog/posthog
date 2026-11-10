import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { dataCatalogNewMetricSceneLogic } from '../dataCatalogNewMetricSceneLogic'
import { QuillMetricFormField } from './QuillMetricFormField'

function NoInsightsMessage({ searching }: { searching: boolean }): JSX.Element {
    if (searching) {
        return <>No insights match this search.</>
    }
    return (
        <>
            No saved insights yet.{' '}
            <Button variant="link" size="inline" render={<LinkPrimitive to={urls.insightNew()} />}>
                Create an insight
            </Button>
        </>
    )
}

export function QuillNewMetricInsightDefinition(): JSX.Element {
    const {
        savedInsights,
        savedInsightsLoading,
        savedInsightsFailed,
        insightSearch,
        selectedInsight,
        metricsUsingSelectedInsight,
    } = useValues(dataCatalogNewMetricSceneLogic)
    const { setInsightSearch, loadSavedInsights } = useActions(dataCatalogNewMetricSceneLogic)
    const labelByShortId = new Map(savedInsights.map((insight) => [insight.short_id, insight.label]))

    return (
        <div className="flex flex-col gap-2">
            {savedInsightsFailed && (
                <Item variant="outline" size="sm" tone="destructive">
                    <ItemContent>
                        <ItemDescription>Couldn't load your saved insights.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={() => loadSavedInsights(undefined)}>
                            Retry
                        </Button>
                    </ItemActions>
                </Item>
            )}
            <QuillMetricFormField
                name="sourceInsightShortId"
                description="The metric copies this insight's query. Later insight edits show as drift; they don't update the metric."
            >
                {({ id, value, onChange, invalid }) => (
                    <Combobox
                        items={savedInsights.map((insight) => insight.short_id)}
                        value={value || null}
                        filter={null}
                        onValueChange={(next: string | null) => onChange(next || '')}
                        onInputValueChange={(search: string, { reason }) => {
                            if (reason === 'input-change' || reason === 'input-clear') {
                                setInsightSearch(search)
                            }
                        }}
                        itemToStringLabel={(shortId: string) => labelByShortId.get(shortId) ?? shortId}
                    >
                        <ComboboxInput
                            id={id}
                            placeholder={savedInsightsLoading ? 'Loading...' : 'Search saved insights'}
                            aria-invalid={invalid || undefined}
                            data-attr="data-catalog-new-metric-insight"
                        />
                        <ComboboxContent>
                            <ComboboxEmpty>
                                {savedInsightsLoading ? (
                                    'Loading...'
                                ) : (
                                    <NoInsightsMessage searching={!!insightSearch} />
                                )}
                            </ComboboxEmpty>
                            <ComboboxList>
                                {(shortId: string) => (
                                    <ComboboxItem key={shortId} value={shortId}>
                                        <span className="truncate">{labelByShortId.get(shortId)}</span>
                                    </ComboboxItem>
                                )}
                            </ComboboxList>
                        </ComboboxContent>
                    </Combobox>
                )}
            </QuillMetricFormField>
            {selectedInsight && (
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Text size="xs" weight="semibold" className="m-0 truncate" render={<span />}>
                        {selectedInsight.label}
                    </Text>
                    {selectedInsight.typeName && <Badge>{selectedInsight.typeName}</Badge>}
                    <Text size="xs" render={<span />}>
                        <Button
                            variant="link"
                            size="inline"
                            render={
                                <LinkPrimitive
                                    to={urls.insightView(selectedInsight.short_id as InsightShortId)}
                                    target="_blank"
                                />
                            }
                        >
                            Open insight
                        </Button>
                    </Text>
                </div>
            )}
            {metricsUsingSelectedInsight.length > 0 && (
                <Text size="xs" variant="muted" className="m-0">
                    Already used by:{' '}
                    {metricsUsingSelectedInsight.map((name, index) => (
                        <span key={name}>
                            {index > 0 && ', '}
                            <code>{name}</code>
                        </span>
                    ))}
                </Text>
            )}
        </div>
    )
}
