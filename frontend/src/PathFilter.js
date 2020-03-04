import React from 'react'
import DatePicker from 'react-datepicker'

export default function PathFilter ({ filter: { startDate, endDate }, updateFilter }) {
  return (
    <div className='row' style={{margin: '1rem -15px'}}>
      <div className='col-3'>
        <div className='label'>Start Date</div>
        <DatePicker selected={startDate} onChange={date => updateFilter({ startDate: date })} />
      </div>
      <div className='col-3'>
        <div className='label'>End Date</div>
        <DatePicker selected={endDate} onChange={date => updateFilter({ endDate: date })} />
      </div>
    </div>
  )
}
