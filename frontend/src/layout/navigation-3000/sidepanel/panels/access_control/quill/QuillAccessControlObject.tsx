import { BindLogic, useValues } from 'kea'

import { IconInfo, IconLock } from '@posthog/icons'
import {
    Button,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { AvailableFeature } from '~/types'

import { AccessControlLogicProps, accessControlLogic } from '../accessControlLogic'
import { QuillAccessControlDefaults } from './QuillAccessControlDefaults'
import { QuillAccessControlMembers } from './QuillAccessControlMembers'
import { QuillAccessControlRoles } from './QuillAccessControlRoles'

export function QuillAccessControlObject(props: AccessControlLogicProps): JSX.Element {
    const { canEditAccessControls, humanReadableResource, resource } = useValues(accessControlLogic(props))

    const suffix = `this ${humanReadableResource}`
    const tooltipText = getAccessControlTooltip(resource)

    return (
        <BindLogic logic={accessControlLogic} props={props}>
            <div className="flex flex-col gap-6">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-1">
                        <Heading size="base" render={<h2 className="m-0" />}>
                            {props.title}
                        </Heading>
                        {tooltipText && (
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={<Button size="icon-xs" aria-label="About object permissions" />}
                                >
                                    <IconInfo />
                                </TooltipTrigger>
                                <TooltipContent>{tooltipText}</TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                    <Text size="xs" variant="muted">
                        {props.description}
                    </Text>
                </div>
                <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="access-control-object-settings">
                    <div className="flex flex-col gap-6">
                        {canEditAccessControls === false && (
                            <Item variant="outline" tone="warning" size="sm">
                                <ItemMedia variant="icon">
                                    <IconLock />
                                </ItemMedia>
                                <ItemContent>
                                    <ItemTitle>Permission required</ItemTitle>
                                    <ItemDescription>
                                        Only the creator of {suffix}, project admins, organization admins, or people
                                        with manager access to it can change its access.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}

                        <section className="flex flex-col gap-2">
                            <Heading size="sm" render={<h3 className="m-0" />}>
                                Default access to {suffix}
                            </Heading>
                            <div>
                                <QuillAccessControlDefaults />
                            </div>
                        </section>

                        <QuillAccessControlMembers />

                        {/* Inside the access control gate, so the two pay gates never show at once */}
                        <PayGateMini
                            feature={AvailableFeature.ROLE_BASED_ACCESS}
                            featureDetail="access-control-object-roles"
                        >
                            <QuillAccessControlRoles />
                        </PayGateMini>
                    </div>
                </PayGateMini>
            </div>
        </BindLogic>
    )
}
