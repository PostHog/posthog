import type {
    DashboardV2DashboardLinkApi,
    DashboardV2DrilldownApi,
    DashboardV2FieldConfigApi,
    DashboardV2FieldOverrideApi,
    DashboardV2MappingApi,
    DashboardV2PanelApi,
    DashboardV2PanelItemApi,
    DashboardV2RowItemApi,
    DashboardV2SpecApi,
    DashboardV2TabsItemApi,
    DashboardV2TargetApi,
    DashboardV2ThresholdApi,
} from './generated/api.schemas'

// A stored document never holds null: the server leaves unset keys out. The generated types allow it, so strip it here.
type WithoutNull<T> = T extends null
    ? never
    : T extends (infer Item)[]
      ? WithoutNull<Item>[]
      : T extends object
        ? { [Key in keyof T]: WithoutNull<T[Key]> }
        : T

export type Dashboard = WithoutNull<DashboardV2SpecApi>
export type Panel = WithoutNull<DashboardV2PanelApi>
export type Target = WithoutNull<DashboardV2TargetApi>
export type Variable = Dashboard['variables'] extends (infer Item)[] | undefined ? Item : never
export type Transform = NonNullable<Panel['transforms']>[number]
export type FieldConfig = WithoutNull<DashboardV2FieldConfigApi>
export type FieldOverride = WithoutNull<DashboardV2FieldOverrideApi>
export type Mapping = WithoutNull<DashboardV2MappingApi>
export type Threshold = WithoutNull<DashboardV2ThresholdApi>
export type Drilldown = WithoutNull<DashboardV2DrilldownApi>
export type DashboardLink = WithoutNull<DashboardV2DashboardLinkApi>
export type PanelItem = WithoutNull<DashboardV2PanelItemApi>
export type RowItem = WithoutNull<DashboardV2RowItemApi>
export type TabsItem = WithoutNull<DashboardV2TabsItemApi>
export type QueryLanguage = Target['language']
export type Display = NonNullable<Dashboard['display']>
