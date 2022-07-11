import React from 'react'
import { useActions, useValues } from 'kea'
import { EditorFilterProps, PathType } from '~/types'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { PathItemFilters } from 'lib/components/PropertyFilters/PathItemFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function PathsExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter, wildcards } = useValues(pathsLogic(insightProps))
    const { updateExclusions } = useActions(pathsLogic(insightProps))

    const taxonomicGroupTypes: TaxonomicFilterGroupType[] = filter.include_event_types
        ? [
              ...filter.include_event_types.map((item) => {
                  if (item === PathType.Screen) {
                      return TaxonomicFilterGroupType.Screens
                  } else if (item === PathType.CustomEvent) {
                      return TaxonomicFilterGroupType.CustomEvents
                  } else {
                      return TaxonomicFilterGroupType.PageviewUrls
                  }
              }),
              TaxonomicFilterGroupType.Wildcards,
          ]
        : [TaxonomicFilterGroupType.Wildcards]

    return (
        <PathItemFilters
            taxonomicGroupTypes={taxonomicGroupTypes}
            pageKey={'exclusion'}
            propertyFilters={
                filter.exclude_events &&
                filter.exclude_events.map((name) => ({
                    key: name,
                    value: name,
                    operator: null,
                    type: 'event',
                }))
            }
            onChange={(values) => {
                const exclusion = values.length > 0 ? values.map((v) => v.value) : values
                updateExclusions(exclusion as string[])
            }}
            wildcardOptions={wildcards}
        />
    )
}
