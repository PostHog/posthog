import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconFolder } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { LibraryCreateButton } from 'scenes/library/LibraryCreateButton'
import { libraryLogic } from 'scenes/library/libraryLogic'
import { libraryListHref, libraryTypeForPath } from 'scenes/library/libraryUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayPaneRow } from './TodayPaneRow'
import { matchesPaneQuery } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'

/** The Library sub-nav: every saved object type, each opening a filtered list in the main area. */
export function TodayLibrarySidebar(): JSX.Element {
    const { objectTypes } = useValues(libraryLogic)
    const { location } = useValues(router)
    const [query, setQuery] = useState('')
    const path = removeProjectIdIfPresent(location.pathname)
    const objectPageType = libraryTypeForPath(path)

    const showAll = matchesPaneQuery('All objects', query)
    const types = objectTypes.filter((type) => matchesPaneQuery(type.pluralLabel, query))

    return (
        <div className="TodayPane" data-quill>
            <TodayPaneSearchList
                query={query}
                onQueryChange={setQuery}
                searchLabel="Search library"
                dataAttr="today-library-search"
            >
                {!showAll && !types.length && (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        Nothing in Library matches that search.
                    </Text>
                )}
                {(showAll || types.length > 0) && (
                    <div>
                        {showAll && (
                            <TodayPaneRow
                                value="all"
                                label="All objects"
                                icon={<IconFolder />}
                                to={urls.library()}
                                active={path === urls.library()}
                                dataAttr="today-library-all"
                            />
                        )}
                        {types.map((type) => (
                            <TodayPaneRow
                                key={type.value}
                                value={`type:${type.value}`}
                                label={type.pluralLabel}
                                icon={iconForType(type.value as FileSystemIconType)}
                                to={libraryListHref(type.value) ?? urls.library(type.value)}
                                active={path === urls.library(type.value) || objectPageType === type.value}
                                action={<LibraryCreateButton objectType={type.value} />}
                                dataAttr="today-library-type"
                            />
                        ))}
                    </div>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
