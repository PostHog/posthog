package com.example.backend.services;

import java.util.ArrayList;
import java.util.List;
import java.util.Properties;

import org.springframework.stereotype.Service;

import com.example.backend.model.*;

import java.sql.*;

/**
 * eventsService
 */
@Service
public class eventsService {

    private final String url = "jdbc:ch://localhost:8123?jdbc_ignore_unsupported_values=true&socket_timeout=10";
    private final String username = "default";
    private final String password = "";
    private Statement st;

    eventsService() {
        try {
            Connection con = DriverManager.getConnection(url, username, password);
            System.out.println("Connection is successfully");

            st = con.createStatement();
        } catch (SQLException ex) {
            System.out.println(ex);
        }
    }

    public List<apiHeatmapGetDTO> getAllHeatmap(String query) {
        List<apiHeatmapGetDTO> results = new ArrayList<>();
        try {
            HeatmapQueryParams qry = new HeatmapQueryParams(query);
            StringBuilder sql = new StringBuilder(
                    "SELECT * FROM events WHERE event = $$heatmap");

//            sql.append(" And timestamp >= " + qry.getDateFrom());

            ResultSet rs = st.executeQuery(sql.toString());
            while (rs.next()) {
                List<apiHeatmapGetDTO> heatmap = new ArrayList<>();
                float viewPortWidth = 1;
                String properties = rs.getString("properties");
                for (String property : properties.split(",")) {
                    String[] values = property.split(":");
                    if(values[0].isEmpty() || values[0].isBlank()) continue;
                    if(values[0].equals("$heatmap_data")) {
                        if(values[1].isEmpty() || values[1].isBlank()) continue;
                        if(values[1].charAt(0) == '{') {
                            values[1] = values[1].substring(1, values[1].length() - 1);
                        }
                        String[] dataValues = values[1].split(":");
                        if(dataValues[0].isEmpty() || dataValues[0].isBlank() || !qry.getUrlExact().equals(dataValues[0])) continue;
                        if(dataValues[1].isEmpty() || dataValues[1].isBlank()) continue;
                        for(String mouseValue : dataValues[1].split(",")) {
                            if(mouseValue.isBlank()) continue;
                            if(mouseValue.charAt(0) == '{') {
                                mouseValue = mouseValue.substring(1, mouseValue.length() - 1);
                            }
                            String[] eachMouseValues = mouseValue.split(",");
                            apiHeatmapGetDTO heatmapDTO = new apiHeatmapGetDTO();
                            heatmapDTO.setPointer_y(Integer.parseInt(eachMouseValues[3].split(":")[1]));
                            heatmapDTO.setPointer_relative_x(Integer.parseInt(eachMouseValues[2].split(":")[1]));
                            heatmapDTO.setPointer_target_fixed(false);
                            heatmapDTO.setCount(1);
                            heatmap.add(heatmapDTO);
                        }
                    } else if(values[0].equals("viewport_width)")) {
                        viewPortWidth = Integer.parseInt(values[1]);
                    }
                }
                for(apiHeatmapGetDTO heatmapData : heatmap) {
                    heatmapData.setPointer_relative_x(heatmapData.getPointer_relative_x() / viewPortWidth);
                    results.add(heatmapData);
                }
            }
        } catch (Exception ex) {
            System.out.println(ex);
        }
        return results;
    }
}
