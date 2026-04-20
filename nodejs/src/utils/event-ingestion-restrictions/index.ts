// Public API
export { EventIngestionRestrictionManager, IngestionPipeline } from './manager'
export { REDIS_KEY_PREFIX, RedisRestrictionType } from './redis-schema'
export {
    EventContext,
    RestrictionFilters,
    RestrictionMap,
    RestrictionRule,
    RestrictionScope,
    RestrictionType,
} from './rules'

// Backward compatibility alias
export { RestrictionType as Restriction } from './rules'
