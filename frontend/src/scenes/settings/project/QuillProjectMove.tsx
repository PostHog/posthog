import { IconArrowRight } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Text,
} from '@posthog/quill'

import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'

import { OrganizationBasicType } from '~/types'

export function QuillProjectMove({
    projectName,
    organizations,
    getOrganizationDisabledReason,
    targetOrganizationId,
    onTargetOrganizationChange,
    selectDisabledReason,
    onMoveClick,
    moveDisabledReason,
}: {
    projectName: string | undefined
    organizations: OrganizationBasicType[]
    getOrganizationDisabledReason: (organization: OrganizationBasicType) => string | undefined
    targetOrganizationId: string | null
    onTargetOrganizationChange: (organizationId: string | null) => void
    selectDisabledReason: string | null
    onMoveClick: () => void
    moveDisabledReason: string | undefined
}): JSX.Element {
    const organizationsById = new Map(organizations.map((organization) => [organization.id, organization]))

    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" render={<p className="m-0" />}>
                Move <b>{projectName}</b> to another organization?
            </Text>
            <div className="flex flex-wrap items-center gap-2">
                <Combobox
                    items={organizations.map((organization) => organization.id)}
                    value={targetOrganizationId}
                    onValueChange={onTargetOrganizationChange}
                    itemToStringLabel={(organizationId: string) =>
                        organizationsById.get(organizationId)?.name ?? organizationId
                    }
                >
                    <ComboboxInput
                        className="min-w-60 flex-1"
                        placeholder="Select target organization"
                        aria-label="Target organization"
                        disabledReason={selectDisabledReason}
                        data-attr="move-project-target-organization-search"
                    />
                    <ComboboxContent>
                        <ComboboxEmpty>No organizations match</ComboboxEmpty>
                        <ComboboxList>
                            {(organizationId: string) => {
                                const organization = organizationsById.get(organizationId)

                                return (
                                    <ComboboxItem
                                        key={organizationId}
                                        value={organizationId}
                                        disabledReason={
                                            organization ? getOrganizationDisabledReason(organization) : undefined
                                        }
                                    >
                                        {organization && (
                                            <UploadedLogo
                                                size="xsmall"
                                                name={organization.name}
                                                entityId={organization.id}
                                                mediaId={organization.logo_media_id}
                                            />
                                        )}
                                        {organization?.name ?? organizationId}
                                    </ComboboxItem>
                                )
                            }}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
                <Button
                    variant="destructive-outline"
                    onClick={onMoveClick}
                    data-attr="move-project-button"
                    disabledReason={moveDisabledReason}
                >
                    <IconArrowRight />
                    Move {projectName || 'the current project'}
                </Button>
            </div>
        </div>
    )
}
