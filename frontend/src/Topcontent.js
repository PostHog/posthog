import React, { Component } from 'react'
import { NavLink } from 'react-router-dom';

export default class Topcontent extends Component {
    render() {
        return (
        	<div>
		        <div class="row right-align">
		          <div class="col-4">
		            <i className='fi flaticon-down-arrow-1' /> Export
		          </div>
		          <div class="col-4">
		            <i className='fi flaticon-settings' /> Settings
		          </div>
		          <div class="col-4">
		            <i className='fi flaticon-user-1' /> Profile
		          </div>
		        </div>
		    </div>
        )
    }
}