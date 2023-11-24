// NOTE: All exported items from the EE module _must_ be optionally defined to ensure we work well with FOSS
export type PostHogEE = {
    enabled: boolean
    myTestCode?: () => void
}
