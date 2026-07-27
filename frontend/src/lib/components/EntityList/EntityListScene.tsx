import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { pluralize } from 'lib/utils/strings'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { entityListLogic } from './entityListLogic'
import { registerEntityList, resolveEntityListMeta } from './entityListRegistry'
import { EntityListDefinition } from './types'

/**
 * Builds a scene from an entity list definition and registers it, so the list is reachable both as a
 * route and by type. The definition supplies the rows; loading, searching, sorting, paging, URL sync
 * and the surrounding scene chrome come from here.
 */
export function defineEntityListScene<T extends Record<string, any>>(
    definition: EntityListDefinition<T>
): SceneExport<{ definition: EntityListDefinition<T> }> {
    registerEntityList(definition)

    return {
        component: function EntityListSceneComponent() {
            return <EntityListScene definition={definition} />
        },
        logic: entityListLogic,
        paramsToProps: () => ({ definition }),
        productKey: definition.productKey,
        emptyState: definition.emptyState,
    }
}

export function EntityListScene<T extends Record<string, any>>({
    definition,
}: {
    definition: EntityListDefinition<T>
}): JSX.Element {
    const logic = entityListLogic({ definition })
    const { results, entitiesLoading, filters, pagination, sorting, count, isEmpty, isNarrowed, loadError } =
        useValues(logic)
    const { setFilters, loadEntities } = useActions(logic)

    const meta = resolveEntityListMeta(definition)
    const rowKey = definition.rowKey ?? 'id'
    const isServerMode = definition.mode === 'server'

    const nameColumn: LemonTableColumn<T, undefined> = {
        title: definition.nameColumn.title ?? 'Name',
        key: definition.nameColumn.key ?? 'name',
        width: definition.nameColumn.width,
        sorter: definition.nameColumn.sorter,
        render: (_, record) => (
            <LemonTableLink
                to={definition.nameColumn.to?.(record) ?? meta.detailUrl?.(String(record[rowKey]))}
                title={definition.nameColumn.render(record)}
                description={definition.nameColumn.description?.(record)}
            />
        ),
    }

    const menuColumn: LemonTableColumn<T, undefined>[] = definition.rowMenu
        ? [
              {
                  width: 0,
                  render: (_, record) => (
                      <More overlay={definition.rowMenu?.(record, { refresh: () => loadEntities() })} />
                  ),
              },
          ]
        : []

    const columns = [nameColumn, ...definition.columns, ...menuColumn] as LemonTableColumns<T>

    return (
        <SceneContent>
            <SceneTitleSection
                name={meta.name}
                description={meta.description}
                resourceType={{ type: meta.iconType }}
                actions={
                    <>
                        {definition.newButton ? <NewEntityButton definition={definition} /> : null}
                        {definition.extraActions}
                    </>
                }
            />

            {definition.banner?.({ isEmpty, isNarrowed })}

            {definition.search && !(isEmpty && definition.hideTableWhenEmpty) && (
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <LemonInput
                        className="w-60"
                        type="search"
                        placeholder={definition.search.placeholder}
                        value={filters.search}
                        onChange={(search) => setFilters({ search })}
                        allowClear
                        data-attr={`${definition.type}-list-search`}
                    />
                    <span className="text-secondary">{pluralize(count, ...meta.nouns)}</span>
                </div>
            )}

            {isEmpty && definition.hideTableWhenEmpty ? null : (
                <LemonTable
                    id={`${definition.type}-list`}
                    columns={columns}
                    dataSource={results as T[]}
                    rowKey={rowKey}
                    loading={entitiesLoading}
                    pagination={pagination}
                    nouns={meta.nouns}
                    sorting={isServerMode ? sorting : undefined}
                    // In server mode the logic owns the ordering param, so LemonTable must not also write one.
                    useURLForSorting={!isServerMode}
                    onSort={
                        isServerMode
                            ? (newSorting) =>
                                  setFilters({
                                      orderBy: newSorting
                                          ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                          : null,
                                  })
                            : undefined
                    }
                    emptyState={
                        loadError ? (
                            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadEntities() }}>
                                {loadError}
                            </LemonBanner>
                        ) : isNarrowed ? (
                            `No ${meta.nouns[1]} match your search`
                        ) : undefined
                    }
                    data-attr={`${definition.type}-list-table`}
                />
            )}
        </SceneContent>
    )
}

function NewEntityButton({ definition }: { definition: EntityListDefinition<any> }): JSX.Element | null {
    const newButton = definition.newButton
    if (!newButton) {
        return null
    }

    const button = (
        <LemonButton
            type="primary"
            size="small"
            to={typeof newButton.to === 'function' ? newButton.to() : newButton.to}
            onClick={newButton.onClick}
            disabledReason={newButton.disabledReason?.()}
            data-attr={newButton['data-attr']}
            tooltip={newButton.label}
            sideAction={newButton.sideAction}
        >
            {newButton.label}
        </LemonButton>
    )

    if (!newButton.shortcutName) {
        return button
    }

    return (
        <Shortcut
            name={newButton.shortcutName}
            keybind={[keyBinds.new]}
            intent={newButton.label}
            interaction="click"
            // A few Scene values differ from their enum keys (the error and create scenes), which is why
            // Shortcut keys its scope by name. An entity list is never one of those.
            scope={definition.scene as keyof typeof Scene}
        >
            {button}
        </Shortcut>
    )
}
