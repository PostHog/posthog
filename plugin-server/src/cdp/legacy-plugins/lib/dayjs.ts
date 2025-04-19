import dayjs from 'dayjs'
import advancedFormat from 'dayjs/plugin/advancedFormat'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)
dayjs.extend(advancedFormat)

export default dayjs
