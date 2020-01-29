import React, { Component } from 'react'
import { NavLink } from 'react-router-dom';

export default class Topcontent extends Component {
    render() {
        return (
        	<div>
		        <div class="right-align">
		            <i className='fi flaticon-user-1' /> {this.props.user.email}
		        </div>
		    </div>
        )
    }
}