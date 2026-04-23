import { BotCategory, CATEGORY_LABELS } from 'lib/utils/botDetection'

import {
    BotBreakdownItem,
    BrowserBreakdownItem,
    CountryBreakdownItem,
    ReferrerItem,
    SlidingWindowBucket,
} from './LiveWebAnalyticsMetricsTypes'

export class LiveMetricsSlidingWindow {
    private buckets = new Map<number, SlidingWindowBucket>()
    private windowSizeSeconds: number

    // Tracks unique counts across all buckets
    private userBucketCounts = new Map<string, number>()
    private deviceBucketCounts = new Map<string, Map<string, number>>()
    private browserBucketCounts = new Map<string, Map<string, number>>()
    private countryBucketCounts = new Map<string, Map<string, number>>()

    // Incrementally-maintained aggregates
    private _totalPageviews = 0
    private _globalPathCounts = new Map<string, number>()
    private _globalReferrerCounts = new Map<string, number>()
    private _globalBotCounts = new Map<string, number>()
    private _globalBotCategoryCounts = new Map<string, number>()
    private _botNameToCategory = new Map<string, string>()

    constructor(windowSizeMinutes: number) {
        this.windowSizeSeconds = windowSizeMinutes * 60
    }

    addDataPoint(
        eventTs: number,
        distinctId: string,
        data: {
            pageviews?: number
            pathname?: string
            referringDomain?: string
            device?: { deviceId: string; deviceType: string }
            browser?: { deviceId: string; browserType: string }
            bot?: { name: string; category: string }
        }
    ): void {
        const bucket = this.getOrCreateBucket(eventTs)

        this.addUserToBucket(bucket, distinctId)

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
            this._totalPageviews += data.pageviews
        }

        if (data.pathname) {
            bucket.paths.set(data.pathname, (bucket.paths.get(data.pathname) || 0) + 1)
            this._globalPathCounts.set(data.pathname, (this._globalPathCounts.get(data.pathname) || 0) + 1)
        }

        if (data.referringDomain) {
            bucket.referrers.set(data.referringDomain, (bucket.referrers.get(data.referringDomain) || 0) + 1)
            this._globalReferrerCounts.set(
                data.referringDomain,
                (this._globalReferrerCounts.get(data.referringDomain) || 0) + 1
            )
        }

        if (data.device) {
            this.addDeviceToBucket(bucket, data.device.deviceType, data.device.deviceId)
        }

        if (data.browser) {
            this.addBrowserToBucket(bucket, data.browser.browserType, data.browser.deviceId)
        }

        if (data.bot) {
            this.addBotToBucket(bucket, data.bot.name, data.bot.category)
        }
    }

    addGeoDataPoint(eventTs: number, countryCode: string, distinctId: string): void {
        if (!countryCode || !distinctId) {
            return
        }
        const bucket = this.getOrCreateBucket(eventTs)
        this.addCountryToBucket(bucket, countryCode, distinctId)
    }

    extendBucketData(eventTs: number, data: SlidingWindowBucket): void {
        const bucket = this.getOrCreateBucket(eventTs)

        if (data.uniqueUsers) {
            for (const distinctId of data.uniqueUsers) {
                this.addUserToBucket(bucket, distinctId)
            }
        }

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
            this._totalPageviews += data.pageviews
        }

        if (data.devices) {
            for (const [deviceType, deviceIds] of data.devices) {
                for (const deviceId of deviceIds) {
                    this.addDeviceToBucket(bucket, deviceType, deviceId)
                }
            }
        }

        if (data.browsers) {
            for (const [browserType, deviceIds] of data.browsers) {
                for (const deviceId of deviceIds) {
                    this.addBrowserToBucket(bucket, browserType, deviceId)
                }
            }
        }

        if (data.paths) {
            for (const [path, count] of data.paths) {
                bucket.paths.set(path, (bucket.paths.get(path) || 0) + count)
                this._globalPathCounts.set(path, (this._globalPathCounts.get(path) || 0) + count)
            }
        }

        if (data.referrers) {
            for (const [referrer, count] of data.referrers) {
                bucket.referrers.set(referrer, (bucket.referrers.get(referrer) || 0) + count)
                this._globalReferrerCounts.set(referrer, (this._globalReferrerCounts.get(referrer) || 0) + count)
            }
        }

        if (data.countries) {
            for (const [countryCode, userIds] of data.countries) {
                for (const userId of userIds) {
                    this.addCountryToBucket(bucket, countryCode, userId)
                }
            }
        }

        if (data.bots) {
            for (const [botName, entry] of data.bots) {
                this.addBotToBucketBulk(bucket, botName, entry.category, entry.count)
            }
        }
    }

    private addUserToBucket(bucket: SlidingWindowBucket, userId: string): void {
        if (!bucket.uniqueUsers.has(userId)) {
            bucket.uniqueUsers.add(userId)

            const prevCount = this.userBucketCounts.get(userId) || 0
            this.userBucketCounts.set(userId, prevCount + 1)

            // Classify as new or returning based on whether we've seen this user globally
            if (prevCount > 0) {
                bucket.returningUserCount++
            } else {
                bucket.newUserCount++
            }
        }
    }

    private addItemToBucket(
        bucketMap: Map<string, Set<string>>,
        globalCounts: Map<string, Map<string, number>>,
        itemType: string,
        itemId: string
    ): void {
        const bucketIds = bucketMap.get(itemType) ?? new Set<string>()

        if (!bucketIds.has(itemId)) {
            bucketIds.add(itemId)
            bucketMap.set(itemType, bucketIds)

            const typeCounts = globalCounts.get(itemType) ?? new Map<string, number>()
            typeCounts.set(itemId, (typeCounts.get(itemId) || 0) + 1)
            globalCounts.set(itemType, typeCounts)
        }
    }

    private addDeviceToBucket(bucket: SlidingWindowBucket, deviceType: string, deviceId: string): void {
        this.addItemToBucket(bucket.devices, this.deviceBucketCounts, deviceType, deviceId)
    }

    private addBrowserToBucket(bucket: SlidingWindowBucket, browserType: string, deviceId: string): void {
        this.addItemToBucket(bucket.browsers, this.browserBucketCounts, browserType, deviceId)
    }

    private addBotToBucket(bucket: SlidingWindowBucket, botName: string, category: string): void {
        this.addBotToBucketBulk(bucket, botName, category, 1)
    }

    private addBotToBucketBulk(bucket: SlidingWindowBucket, botName: string, category: string, count: number): void {
        if (!bucket.bots) {
            bucket.bots = new Map<string, { count: number; category: string }>()
        }
        const existing = bucket.bots.get(botName)
        bucket.bots.set(botName, { count: (existing?.count ?? 0) + count, category })

        this._globalBotCounts.set(botName, (this._globalBotCounts.get(botName) || 0) + count)
        this._globalBotCategoryCounts.set(category, (this._globalBotCategoryCounts.get(category) || 0) + count)
        this._botNameToCategory.set(botName, category)
    }

    private addCountryToBucket(bucket: SlidingWindowBucket, countryCode: string, distinctId: string): void {
        const bucketUserIds = bucket.countries.get(countryCode) ?? new Set<string>()

        if (!bucketUserIds.has(distinctId)) {
            bucketUserIds.add(distinctId)
            bucket.countries.set(countryCode, bucketUserIds)

            // Update global tracking
            const countryCounts = this.countryBucketCounts.get(countryCode) ?? new Map<string, number>()
            countryCounts.set(distinctId, (countryCounts.get(distinctId) || 0) + 1)
            this.countryBucketCounts.set(countryCode, countryCounts)
        }
    }

    private removeUsersFromTracking(bucket: SlidingWindowBucket): void {
        for (const userId of bucket.uniqueUsers) {
            const count = this.userBucketCounts.get(userId) || 0
            if (count <= 1) {
                this.userBucketCounts.delete(userId)
            } else {
                this.userBucketCounts.set(userId, count - 1)
            }
        }
    }

    private removeItemsFromTracking(
        bucketMap: Map<string, Set<string>>,
        globalCounts: Map<string, Map<string, number>>
    ): void {
        for (const [itemType, itemIds] of bucketMap) {
            const typeCounts = globalCounts.get(itemType)
            if (!typeCounts) {
                continue
            }

            for (const itemId of itemIds) {
                const count = typeCounts.get(itemId) || 0
                if (count <= 1) {
                    typeCounts.delete(itemId)
                } else {
                    typeCounts.set(itemId, count - 1)
                }
            }

            if (typeCounts.size === 0) {
                globalCounts.delete(itemType)
            }
        }
    }

    private removeCountriesFromTracking(bucket: SlidingWindowBucket): void {
        for (const [countryCode, userIds] of bucket.countries) {
            const countryCounts = this.countryBucketCounts.get(countryCode)
            if (!countryCounts) {
                continue
            }

            for (const userId of userIds) {
                const count = countryCounts.get(userId) || 0
                if (count <= 1) {
                    countryCounts.delete(userId)
                } else {
                    countryCounts.set(userId, count - 1)
                }
            }

            // Clean up empty country maps
            if (countryCounts.size === 0) {
                this.countryBucketCounts.delete(countryCode)
            }
        }
    }

    private decrementGlobalCounts(bucketMap: Map<string, number>, globalMap: Map<string, number>): void {
        for (const [key, count] of bucketMap) {
            const globalCount = globalMap.get(key) || 0
            if (globalCount <= count) {
                globalMap.delete(key)
            } else {
                globalMap.set(key, globalCount - count)
            }
        }
    }

    prune(): void {
        const nowTs = Date.now() / 1000
        const threshold = nowTs - this.windowSizeSeconds
        for (const [ts, bucket] of this.buckets.entries()) {
            if (ts < threshold) {
                this.removeUsersFromTracking(bucket)
                this.removeItemsFromTracking(bucket.devices, this.deviceBucketCounts)
                this.removeItemsFromTracking(bucket.browsers, this.browserBucketCounts)
                this.removeCountriesFromTracking(bucket)
                this.decrementGlobalCounts(bucket.paths, this._globalPathCounts)
                this.decrementGlobalCounts(bucket.referrers, this._globalReferrerCounts)
                if (bucket.bots) {
                    this.decrementBotCounts(bucket.bots)
                }
                this._totalPageviews -= bucket.pageviews
                this.buckets.delete(ts)
            }
        }
    }

    private decrementBotCounts(botMap: Map<string, { count: number; category: string }>): void {
        for (const [botName, { count, category }] of botMap) {
            const currentCount = this._globalBotCounts.get(botName) || 0
            if (currentCount <= count) {
                this._globalBotCounts.delete(botName)
                this._botNameToCategory.delete(botName)
            } else {
                this._globalBotCounts.set(botName, currentCount - count)
            }

            const currentCategoryCount = this._globalBotCategoryCounts.get(category) || 0
            if (currentCategoryCount <= count) {
                this._globalBotCategoryCounts.delete(category)
            } else {
                this._globalBotCategoryCounts.set(category, currentCategoryCount - count)
            }
        }
    }

    getSortedBuckets(): [number, SlidingWindowBucket][] {
        return [...this.buckets.entries()].sort(([a], [b]) => a - b)
    }

    getTotalPageviews(): number {
        return this._totalPageviews
    }

    getDeviceBreakdown(): { device: string; count: number; percentage: number }[] {
        let total = 0
        const counts: { device: string; count: number }[] = []

        for (const [deviceType, deviceIdCounts] of this.deviceBucketCounts) {
            const count = deviceIdCounts.size
            total += count
            counts.push({ device: deviceType, count })
        }

        if (total === 0) {
            return []
        }

        return counts
            .map(({ device, count }) => ({
                device,
                count,
                percentage: (count / total) * 100,
            }))
            .sort((a, b) => b.count - a.count)
    }

    getBrowserBreakdown(limit?: number): BrowserBreakdownItem[] {
        let total = 0
        const counts: { browser: string; count: number }[] = []

        for (const [browserType, deviceIdCounts] of this.browserBucketCounts) {
            const count = deviceIdCounts.size
            total += count
            counts.push({ browser: browserType, count })
        }

        if (total === 0) {
            return []
        }

        const sorted = counts
            .map(({ browser, count }) => ({
                browser,
                count,
                percentage: (count / total) * 100,
            }))
            .sort((a, b) => b.count - a.count)

        if (!limit || sorted.length <= limit) {
            return sorted
        }

        const top = sorted.slice(0, limit)
        const othersCount = sorted.slice(limit).reduce((sum, item) => sum + item.count, 0)

        if (othersCount > 0) {
            top.push({
                browser: 'Other',
                count: othersCount,
                percentage: (othersCount / total) * 100,
            })
        }

        return top
    }

    getTotalBrowsers(): number {
        let total = 0
        for (const deviceIdCounts of this.browserBucketCounts.values()) {
            total += deviceIdCounts.size
        }
        return total
    }

    getTopPaths(limit: number): { path: string; views: number }[] {
        return this.getTopEntries(this._globalPathCounts, limit).map(([path, views]) => ({ path, views }))
    }

    getTopReferrers(limit: number): ReferrerItem[] {
        return this.getTopEntries(this._globalReferrerCounts, limit).map(([referrer, views]) => ({ referrer, views }))
    }

    private getTopEntries(map: Map<string, number>, limit: number): [string, number][] {
        return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit)
    }

    getCountryBreakdown(): CountryBreakdownItem[] {
        let total = 0
        const counts: { country: string; count: number }[] = []

        for (const [countryCode, userIdCounts] of this.countryBucketCounts) {
            const count = userIdCounts.size
            total += count
            counts.push({ country: countryCode, count })
        }

        if (total === 0) {
            return []
        }

        return counts
            .map(({ country, count }) => ({
                country,
                count,
                percentage: (count / total) * 100,
            }))
            .sort((a, b) => b.count - a.count)
    }

    getTotalUniqueUsers(): number {
        return this.userBucketCounts.size
    }

    getBotBreakdown(limit?: number): BotBreakdownItem[] {
        let total = 0
        for (const count of this._globalBotCounts.values()) {
            total += count
        }

        if (total === 0) {
            return []
        }

        const sorted: BotBreakdownItem[] = [...this._globalBotCounts.entries()]
            .map(([bot, count]) => {
                const categoryKey = (this._botNameToCategory.get(bot) ?? 'regular') as BotCategory
                return {
                    bot,
                    category: CATEGORY_LABELS[categoryKey] ?? categoryKey,
                    count,
                    percentage: (count / total) * 100,
                }
            })
            .sort((a, b) => b.count - a.count)

        if (!limit || sorted.length <= limit) {
            return sorted
        }

        const top = sorted.slice(0, limit)
        const othersCount = sorted.slice(limit).reduce((sum, item) => sum + item.count, 0)

        if (othersCount > 0) {
            top.push({
                bot: 'Other',
                category: '',
                count: othersCount,
                percentage: (othersCount / total) * 100,
            })
        }

        return top
    }

    getTotalBotEvents(): number {
        let total = 0
        for (const count of this._globalBotCounts.values()) {
            total += count
        }
        return total
    }

    getBotCategoryCounts(): Map<string, number> {
        return new Map(this._globalBotCategoryCounts)
    }

    private getOrCreateBucket(eventTs: number): SlidingWindowBucket {
        const bucketTs = Math.floor(eventTs / 60) * 60

        let bucket = this.buckets.get(bucketTs)

        if (!bucket) {
            bucket = {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map<string, Set<string>>(),
                browsers: new Map<string, Set<string>>(),
                paths: new Map<string, number>(),
                referrers: new Map<string, number>(),
                uniqueUsers: new Set<string>(),
                countries: new Map<string, Set<string>>(),
                bots: new Map<string, { count: number; category: string }>(),
            }
            this.buckets.set(bucketTs, bucket)
        }

        return bucket
    }
}
