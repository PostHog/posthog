import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/lib/date-picker/generatePicker'
import './DatePicker.scss'
import { dayjs } from 'lib/dayjs'

export const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)
