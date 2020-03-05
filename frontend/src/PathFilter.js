import React from 'react'
import DatePicker from 'react-datepicker'

export default function PathFilter ({ filter: { startDate, endDate }, updateFilter }) {
  return (
    <div className='row' style={{margin: '1rem -15px'}}>
      <div className='col-3'>
        <label class='control-label' style={{ display: 'block' }}>Start Date</label>
        <DatePicker className='form-control' selected={startDate} onChange={date => updateFilter({ startDate: date })} />
      </div>
      <div className='col-3'>
        <label class='control-label' style={{ display: 'block' }}>End Date</label>
        <DatePicker className='form-control' selected={endDate} onChange={date => updateFilter({ endDate: date })} />
      </div>
    </div>
  )
}
