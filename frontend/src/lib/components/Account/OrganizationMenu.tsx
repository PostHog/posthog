import { useValues } from 'kea'

import { OrgCombobox } from 'lib/components/Account/OrgCombobox'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuOpenIndicator } from 'lib/ui/DropdownMenu/DropdownMenu'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { cn } from 'lib/utils/css-classes'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationMenu({
    buttonProps = { className: 'font-semibold' },
    showName = true,
    allowCreate = true,
    iconOnly = false,
}: {
    showName?: boolean
    buttonProps?: ButtonPrimitiveProps
    allowCreate?: boolean
    iconOnly?: boolean
}): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <>
            <PopoverPrimitive>
                <PopoverPrimitiveTrigger asChild>
                    <ButtonPrimitive
                        iconOnly={iconOnly}
                        data-attr="tree-navbar-organization-dropdown-button"
                        size={iconOnly ? 'base' : 'sm'}
                        {...buttonProps}
                        className={cn('max-w-[178px]', iconOnly ? 'min-w-auto' : '', buttonProps.className)}
                    >
                        {currentOrganization ? (
                            <UploadedLogo
                                name={currentOrganization.name}
                                entityId={currentOrganization.id}
                                mediaId={currentOrganization.logo_media_id}
                                size={iconOnly ? 'small' : 'medium'}
                            />
                        ) : (
                            <UploadedLogo name="?" entityId="" mediaId="" size={iconOnly ? 'xsmall' : 'medium'} />
                        )}
                        {!iconOnly && showName && (
                            <>
                                <span className="truncate font-semibold">
                                    {currentOrganization ? currentOrganization.name : 'Select organization'}
                                </span>
                                <DropdownMenuOpenIndicator />
                            </>
                        )}
                    </ButtonPrimitive>
                </PopoverPrimitiveTrigger>
                <PopoverPrimitiveContent
                    align="start"
                    className="w-[var(--project-panel-inner-width)] max-w-[var(--project-panel-inner-width)]"
                >
                    <OrgCombobox allowCreate={allowCreate} />
                </PopoverPrimitiveContent>
            </PopoverPrimitive>
        </>
    )
}
