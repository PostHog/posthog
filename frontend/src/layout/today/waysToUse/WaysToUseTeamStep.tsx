import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconArrowRight, IconExternal } from '@posthog/icons'
import { Avatar, AvatarFallback, AvatarGroup, AvatarImage, Button, Heading, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { brandingForProduct, brandingForScope } from 'scenes/welcome/productBranding'

import { waysToUseLogic } from './waysToUseLogic'

const MAX_AVATARS = 5

export function WaysToUseTeamStep(): JSX.Element {
    const { teamWork, productsInUse, teamMembers } = useValues(waysToUseLogic)
    const { closeWaysToUse, trackWaysToUseClick } = useActions(waysToUseLogic)
    const workId = useId()
    const productsId = useId()
    const teammatesId = useId()

    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-x-8 gap-y-6 @3xl:min-h-74 @3xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                {teamWork.length > 0 && (
                    <section aria-labelledby={workId} className="flex min-w-0 flex-col gap-2">
                        <Heading id={workId} size="sm" render={<h3 />} className="m-0">
                            Pick up your team's work
                        </Heading>
                        <ul className="-mx-2 m-0 flex list-none flex-col p-0">
                            {teamWork.map((item) => {
                                const Icon = brandingForScope(item.type).branding.Icon
                                return (
                                    <li key={item.url}>
                                        <LinkPrimitive
                                            to={item.url}
                                            onClick={() => closeWaysToUse('surface_link', 'team_work')}
                                            className="group/row flex items-center gap-3 rounded-lg p-2 text-foreground transition-colors hover:bg-fill-hover focus-visible:bg-fill-hover"
                                            data-attr="today-ways-to-use-team-work"
                                        >
                                            <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-background">
                                                <Icon className="size-4" />
                                            </span>
                                            <span className="flex min-w-0 flex-1 flex-col">
                                                <Text size="sm" weight="medium" render={<span />} className="truncate">
                                                    {item.name}
                                                </Text>
                                                <Text size="xs" variant="muted" render={<span />} className="truncate">
                                                    {item.detail}
                                                </Text>
                                            </span>
                                            <IconArrowRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition duration-200 ease-out group-hover/row:translate-x-0.5 group-hover/row:opacity-100 group-focus-visible/row:opacity-100 motion-reduce:transition-none" />
                                        </LinkPrimitive>
                                    </li>
                                )
                            })}
                        </ul>
                    </section>
                )}
                <div className="flex min-w-0 flex-col gap-6">
                    {productsInUse.length > 0 && (
                        <section aria-labelledby={productsId} className="flex flex-col gap-2">
                            <Heading id={productsId} size="sm" render={<h3 />} className="m-0">
                                Products your team uses
                            </Heading>
                            <div className="flex flex-wrap gap-2">
                                {productsInUse.map((productKey) => {
                                    const { label, docsHref, Icon } = brandingForProduct(productKey)
                                    return (
                                        <Button
                                            key={productKey}
                                            size="sm"
                                            variant="outline"
                                            nativeButton={false}
                                            role="link"
                                            render={
                                                <LinkPrimitive
                                                    to={docsHref}
                                                    target="_blank"
                                                    onClick={() => trackWaysToUseClick('product_docs')}
                                                />
                                            }
                                            data-attr="today-ways-to-use-product-docs"
                                        >
                                            <Icon />
                                            {label}
                                            <IconExternal className="text-muted-foreground" />
                                        </Button>
                                    )
                                })}
                            </div>
                        </section>
                    )}
                    {teamMembers.length > 0 && (
                        <section aria-labelledby={teammatesId} className="flex flex-col gap-2">
                            <Heading id={teammatesId} size="sm" render={<h3 />} className="m-0">
                                Your teammates
                            </Heading>
                            <div className="flex flex-wrap items-center gap-3">
                                <AvatarGroup size="sm" className="shrink-0 gap-1">
                                    {teamMembers.slice(0, MAX_AVATARS).map((member) => (
                                        <Avatar key={member.email}>
                                            {member.avatar && <AvatarImage src={member.avatar} alt="" />}
                                            <AvatarFallback className="bg-fill-selected text-xs font-semibold text-foreground">
                                                {(member.name || member.email).charAt(0).toUpperCase()}
                                            </AvatarFallback>
                                        </Avatar>
                                    ))}
                                </AvatarGroup>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    nativeButton={false}
                                    role="link"
                                    render={
                                        <LinkPrimitive
                                            to={urls.settings('organization-members')}
                                            onClick={() => closeWaysToUse('surface_link', 'members')}
                                        />
                                    }
                                    data-attr="today-ways-to-use-members"
                                >
                                    See everyone
                                    <IconArrowRight />
                                </Button>
                            </div>
                        </section>
                    )}
                </div>
            </div>
        </div>
    )
}
