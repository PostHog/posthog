import { dayjs } from 'lib/dayjs'

export const formattedTimestamp = (currentTimestamp: dayjs.Dayjs): string => {
    return currentTimestamp.format('DD/MM/YYYY, HH:mm:ss')
}
