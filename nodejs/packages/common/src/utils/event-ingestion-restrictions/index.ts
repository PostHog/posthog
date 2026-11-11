// Public API
export { EventIngestionRestrictionManager, EventIngestionRestrictionManagerComponent } from './manager'
export type { EventIngestionRestrictionManagerOptions, IngestionPipeline } from './manager'
export { REDIS_KEY_PREFIX, RedisRestrictionType } from './redis-schema'
export { RestrictionFilters, RestrictionMap, RestrictionType } from './rules'
export type { EventContext, RestrictionRule, RestrictionScope } from './rules'

// Backward compatibility alias
export { RestrictionType as Restriction } from './rules'
