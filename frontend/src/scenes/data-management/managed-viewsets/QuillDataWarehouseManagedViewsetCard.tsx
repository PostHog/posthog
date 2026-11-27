import { useId } from 'react'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Field,
    FieldLabel,
    Switch,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AccessControlLevel } from '~/types'

import { DataWarehouseManagedViewsetCardProps } from './DataWarehouseManagedViewsetCard'
import { VIEWSET_DESCRIPTIONS, VIEWSET_TOGGLING_REASON, viewsetToggleLabel } from './managedViewsetCardContent'
import { useManagedViewsetCard } from './useManagedViewsetCard'

/** Quill sibling of `DataWarehouseManagedViewsetCard`. Its callers pick it under `today-rail-nav`. */
export function QuillDataWarehouseManagedViewsetCard({
    type,
    kind,
    resourceType,
    displayDocsLink = true,
    displayConfigLink = true,
}: DataWarehouseManagedViewsetCardProps): JSX.Element | null {
    const switchId = useId()
    const { isEnabled, isToggling, toggleViewset } = useManagedViewsetCard(type, kind)

    const viewsetInfo = VIEWSET_DESCRIPTIONS[kind]

    if (!viewsetInfo) {
        return null
    }

    const { title, description, docsUrl, configUrl, icon } = viewsetInfo

    return (
        <Card>
            <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <CardTitle className="flex items-center gap-2">
                            {icon}
                            {title}
                        </CardTitle>
                        <CardDescription>{description}</CardDescription>
                    </div>
                    <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                        {({ disabledReason }) => (
                            <Field orientation="horizontal" className="w-fit">
                                <Switch
                                    id={switchId}
                                    checked={isEnabled}
                                    onCheckedChange={(enabled: boolean) => toggleViewset(kind, enabled)}
                                    disabledReason={isToggling ? VIEWSET_TOGGLING_REASON : disabledReason}
                                    data-attr="managed-viewset-toggle"
                                />
                                <FieldLabel htmlFor={switchId}>{viewsetToggleLabel(isToggling, isEnabled)}</FieldLabel>
                            </Field>
                        )}
                    </AccessControlAction>
                </div>
            </CardHeader>
            {(displayConfigLink || displayDocsLink) && (
                <CardContent className="flex flex-wrap items-center gap-3">
                    {displayConfigLink && (
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={configUrl} />}
                        >
                            Configure
                        </Button>
                    )}
                    {displayDocsLink && (
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={docsUrl} target="_blank" />}
                        >
                            Learn more in the docs
                        </Button>
                    )}
                </CardContent>
            )}
        </Card>
    )
}
