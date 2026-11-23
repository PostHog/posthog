import { IconBadge } from '@posthog/icons'
import {
    Button,
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AvailableFeature, DataColorThemeModel } from '~/types'

import { DataColorThemeModal } from './DataColorThemeModal'

export function QuillDataColorThemes({
    themes,
    themesLoading,
    defaultThemeId,
    defaultThemeLoading,
    restrictedReason,
    onSelectTheme,
    onDefaultThemeChange,
}: {
    themes: DataColorThemeModel[]
    themesLoading: boolean
    defaultThemeId: number | null
    defaultThemeLoading: boolean
    restrictedReason: string | null
    onSelectTheme: (id: number | 'new') => void
    onDefaultThemeChange: (id: number | null) => void
}): JSX.Element {
    return (
        <PayGateMini feature={AvailableFeature.DATA_COLOR_THEMES} featureDetail="data-color-themes-settings">
            <div className="flex flex-col gap-4">
                <Text size="xs" render={<p className="m-0" />}>
                    These themes can be used in insights. You can also set a default theme for all insights below. For
                    more details, check out our{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/product-analytics/color-themes?utm_campaign=settings&utm_medium=in-product"
                                target="_blank"
                            />
                        }
                    >
                        docs
                    </Button>
                    .
                </Text>
                <div className="flex flex-col items-start gap-2">
                    {themesLoading && themes.length === 0 ? (
                        <div className="flex w-full flex-col gap-2">
                            <Skeleton className="h-8 w-full" />
                            <Skeleton className="h-8 w-full" />
                        </div>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Name</TableHead>
                                    <TableHead>Official</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {themes.map((theme) => (
                                    <TableRow key={theme.id}>
                                        <TableCell>
                                            <Button
                                                variant="link-foreground"
                                                size="sm"
                                                onClick={() => onSelectTheme(theme.id)}
                                            >
                                                {theme.name}
                                            </Button>
                                        </TableCell>
                                        <TableCell>
                                            {theme.is_global ? (
                                                <IconBadge className="text-success-foreground text-xl" />
                                            ) : null}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                    <Button variant="outline" onClick={() => onSelectTheme('new')} disabledReason={restrictedReason}>
                        Add theme
                    </Button>
                </div>

                <Field className="w-fit">
                    <FieldLabel htmlFor="default_theme">Default theme</FieldLabel>
                    <Select<number | null>
                        value={defaultThemeId}
                        onValueChange={onDefaultThemeChange}
                        disabled={defaultThemeLoading}
                    >
                        <SelectTrigger id="default_theme" className="min-w-48" disabledReason={restrictedReason}>
                            <SelectValue>
                                {(selected: number | null) => themes.find((theme) => theme.id === selected)?.name}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {themes.map((theme) => (
                                <SelectItem key={theme.id} value={theme.id}>
                                    {theme.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>

                <DataColorThemeModal />
            </div>
        </PayGateMini>
    )
}
