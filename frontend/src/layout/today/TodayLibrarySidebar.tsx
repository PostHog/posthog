import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { libraryObjectHref, libraryObjectName, todayLibraryLogic } from './todayLibraryLogic'
import { TodayPaneRow } from './TodayPaneRow'

export function TodayLibrarySidebar(): JSX.Element {
    const { objects, objectsLoading, loadFailed, objectTypes, objectType, search, hasMore } =
        useValues(todayLibraryLogic)
    const { setObjectType, setSearch, loadObjects, loadMoreObjects } = useActions(todayLibraryLogic)
    const { location } = useValues(router)
    const typeLabels = Object.fromEntries(objectTypes.map((type) => [type.value, type.label]))

    return (
        <div className="TodayPane">
            <div className="TodayPane__filters">
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search your library"
                    value={search}
                    onChange={setSearch}
                    data-attr="today-library-search"
                    fullWidth
                />
                <LemonSelect
                    size="small"
                    fullWidth
                    value={objectType}
                    onChange={(value) => setObjectType(value ?? '')}
                    options={[{ value: '', label: 'All objects' }, ...objectTypes]}
                    data-attr="today-library-type"
                />
            </div>
            <div className="TodayPane__scroll">
                {objectsLoading && !objects.results.length ? (
                    <div className="TodayPane__state">
                        <Spinner />
                    </div>
                ) : loadFailed && !objects.results.length ? (
                    <div className="TodayPane__state">
                        <span>Your library didn’t load.</span>
                        <LemonButton size="small" type="secondary" onClick={() => loadObjects()}>
                            Try again
                        </LemonButton>
                    </div>
                ) : !objects.results.length ? (
                    <div className="TodayPane__state">
                        {search || objectType
                            ? 'Nothing matches. Try another search or type.'
                            : 'Insights, dashboards, flags and everything else you save show up here.'}
                    </div>
                ) : (
                    <>
                        {objects.results.map((entry) => {
                            const href = libraryObjectHref(entry)
                            const baseType = entry.type?.split('/')[0] ?? ''
                            return (
                                <TodayPaneRow
                                    key={entry.id}
                                    label={libraryObjectName(entry)}
                                    meta={objectType ? undefined : typeLabels[baseType]}
                                    icon={iconForType(entry.type as FileSystemIconType)}
                                    to={href}
                                    active={!!href && location.pathname.endsWith(href.split('?')[0])}
                                    dataAttr="today-library-object"
                                />
                            )
                        })}
                        {hasMore && (
                            <div className="px-2 pt-2">
                                <LemonButton
                                    size="small"
                                    type="tertiary"
                                    fullWidth
                                    center
                                    loading={objectsLoading}
                                    onClick={() => loadMoreObjects()}
                                    data-attr="today-library-load-more"
                                >
                                    Show more
                                </LemonButton>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
