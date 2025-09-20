import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { clickupIntegrationLogic } from './clickupIntegrationLogic'

const getClickUpSpaceOptions = (
    clickUpSpaces?: { id: string; name: string }[] | null
): LemonInputSelectOption[] | null => {
    return clickUpSpaces
        ? clickUpSpaces.map((space) => ({
              key: space.id,
              labelComponent: (
                  <span className="flex items-center">
                      {space.name} ({space.id})
                  </span>
              ),
              label: `${space.name} (${space.id})`,
          }))
        : null
}

const getClickUpWorkspaceOptions = (
    clickUpWorkspaces?: { id: string; name: string }[] | null
): LemonInputSelectOption[] | null => {
    return clickUpWorkspaces
        ? clickUpWorkspaces.map((workspace) => ({
              key: workspace.id,
              labelComponent: (
                  <span className="flex items-center">
                      {workspace.name} ({workspace.id})
                  </span>
              ),
              label: `${workspace.name} (${workspace.id})`,
          }))
        : null
}

const getClickUpListOptions = (
    clickUpLists?: { id: string; name: string }[] | null
): LemonInputSelectOption[] | null => {
    return clickUpLists
        ? clickUpLists.map(({ id, name }) => ({
              key: id,
              labelComponent: (
                  <span className="flex items-center">
                      {name} ({id})
                  </span>
              ),
              label: `${name} (${id})`,
          }))
        : null
}

export type ClickUpPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
    requiresFieldValue?: string
}

export function ClickUpSpacePicker({
    onChange,
    value,
    requiresFieldValue,
    integration,
    disabled,
}: ClickUpPickerProps): JSX.Element {
    const { clickUpSpaces, clickUpSpacesLoading } = useValues(clickupIntegrationLogic({ id: integration.id }))
    const { loadClickUpSpaces } = useActions(clickupIntegrationLogic({ id: integration.id }))

    const clickUpSpaceOptions = useMemo(() => getClickUpSpaceOptions(clickUpSpaces), [clickUpSpaces])

    useEffect(() => {
        if (!disabled && requiresFieldValue) {
            loadClickUpSpaces(requiresFieldValue.split('/')[0])
        }
    }, [loadClickUpSpaces, requiresFieldValue, disabled])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !clickUpSpaces &&
                    !clickUpSpacesLoading &&
                    requiresFieldValue &&
                    loadClickUpSpaces(requiresFieldValue.split('/')[0])
                }
                disabled={disabled}
                mode="single"
                data-attr="select-click-up-space"
                placeholder="Select a Space..."
                options={
                    clickUpSpaceOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value,
                              },
                          ]
                        : [])
                }
                loading={clickUpSpacesLoading}
            />
        </>
    )
}

export function ClickUpWorkspacePicker({ onChange, value, integration, disabled }: ClickUpPickerProps): JSX.Element {
    const { clickUpWorkspaces, clickUpWorkspacesLoading } = useValues(clickupIntegrationLogic({ id: integration.id }))
    const { loadClickUpWorkspaces } = useActions(clickupIntegrationLogic({ id: integration.id }))

    const clickUpWorkspaceOptions = useMemo(() => getClickUpWorkspaceOptions(clickUpWorkspaces), [clickUpWorkspaces])

    useEffect(() => {
        loadClickUpWorkspaces()
    }, [loadClickUpWorkspaces])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() => !clickUpWorkspaces && !clickUpWorkspacesLoading && loadClickUpWorkspaces()}
                disabled={disabled}
                mode="single"
                data-attr="select-click-up-workspace"
                placeholder="Select a Workspace..."
                options={
                    clickUpWorkspaceOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value,
                              },
                          ]
                        : [])
                }
                loading={clickUpWorkspacesLoading}
            />
        </>
    )
}

export function ClickUpListPicker({
    onChange,
    value,
    requiresFieldValue,
    integration,
    disabled,
}: ClickUpPickerProps): JSX.Element {
    const { clickUpLists, clickUpListsLoading } = useValues(clickupIntegrationLogic({ id: integration.id }))
    const { loadClickUpLists } = useActions(clickupIntegrationLogic({ id: integration.id }))

    const clickUpListOptions = useMemo(() => getClickUpListOptions(clickUpLists), [clickUpLists])

    useEffect(() => {
        if (!disabled && requiresFieldValue) {
            loadClickUpLists(requiresFieldValue.split('/')[0])
        }
    }, [loadClickUpLists, disabled, requiresFieldValue])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !clickUpLists &&
                    !clickUpListsLoading &&
                    requiresFieldValue &&
                    loadClickUpLists(requiresFieldValue.split('/')[0])
                }
                disabled={disabled}
                mode="single"
                data-attr="select-click-up-list"
                placeholder="Select a List..."
                options={
                    clickUpListOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value,
                              },
                          ]
                        : [])
                }
                loading={clickUpListsLoading}
            />
        </>
    )
}
