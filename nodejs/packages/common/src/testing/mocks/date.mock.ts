import { DateTime } from 'luxon'

// Helper for mocking the date in tests - works whether local or on CI
const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

export const mockNow = Date.now
