import { TrendsQuery } from '~/queries/schema/schema-general'

export const isBoxPlotMissingProperty = (series: TrendsQuery['series'] | null | undefined): boolean =>
    !series?.length || series.some((s) => !s?.math_property)
