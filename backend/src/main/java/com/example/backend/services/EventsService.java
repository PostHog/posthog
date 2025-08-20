package com.example.backend.services;

import java.text.DecimalFormat;
import java.time.LocalDateTime;
import java.util.*;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.stereotype.Service;

import com.example.backend.model.*;

import java.sql.*;

/**
 * eventsService
 */
@Service
@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class })
public class EventsService {

    private final String url = "jdbc:ch://localhost:8123";
    private final String username = "default";
    private final String password = "";
    private Statement st;

    public EventsService() {
        try {
            Connection con = DriverManager.getConnection(url, username, password);
            System.out.println("Connection is successfully");

            st = con.createStatement();
        } catch (SQLException ex) {
            System.out.println(ex);
        }
    }

    public List<ApiHeatmapGetDTO> getAllHeatmap(String type, String date, String urlExact) {
        Map<KeyMap, Integer> heatmapResult = new HashMap<>();
        List<ApiHeatmapGetDTO> results = new ArrayList<>();
        try {
            urlExact = getUrlExact(urlExact);
            date = getTheDate(date).toString();
            StringBuilder sql = new StringBuilder(
                    "SELECT * FROM events WHERE event = '$$heatmap'");

//            sql.append(" And timestamp >= " + qry.getDateFrom());

            ResultSet rs = st.executeQuery(sql.toString());
            while (rs.next()) {
                List<ApiHeatmapGetDTO> heatmap = new ArrayList<>();
                float viewPortWidth = 1;
                String properties = rs.getString("properties");
                properties = properties.substring(1, properties.length() - 1);
                List<String> listProp = splitOnCommaOutsideBraces(properties, ',');
                for (String property : listProp) {
                    List<String> values = splitOnCommaOutsideBraces(property, ':');
                    if(values.getFirst().charAt(0) == '"') {
                        values.set(0, values.getFirst().substring(1, values.getFirst().length() - 1));
                    }
                    if(values.getFirst().isBlank()) continue;
                    if(values.getFirst().equals("$viewport_width")) {
                        viewPortWidth = Integer.parseInt(values.get(1));
                    }
                }
                for (String property : listProp) {
                    List<String> values = splitOnCommaOutsideBraces(property, ':');
                    if(values.getFirst().charAt(0) == '"') {
                        values.set(0, values.getFirst().substring(1, values.getFirst().length() - 1));
                    }
                    if(values.getFirst().isBlank()) continue;
                    if(values.getFirst().equals("$heatmap_data")) {
                        if (values.get(1).isBlank()) continue;
                        if (values.get(1).charAt(0) == '{') {
                            values.set(1, values.get(1).substring(1, values.get(1).length() - 1));
                        }
                        List<String> dataValues = splitUrlAndProps(values.get(1));
                        dataValues.set(0, dataValues.get(0).substring(1, dataValues.get(0).length() - 1));
                        if (dataValues.get(0).isBlank() || !urlExact.equals(dataValues.get(0))) continue;
                        if (dataValues.get(1).isBlank()) continue;
                        dataValues.set(1, dataValues.get(1).substring(1, dataValues.get(1).length() - 1));
                        List<String> eachMouseValues = splitOnCommaOutsideBraces(dataValues.get(1), ',');
                        for (String value : eachMouseValues) {
                            value = value.substring(1, value.length() - 1);
                            String[] mouseValues = value.split(",");
                            if (!mouseValues[1].split(":")[1].equals('"' + type + '"')) {
                                continue;
                            }
                            KeyMap keyMap = new KeyMap();
                            keyMap.y = (toNearestFive(Integer.parseInt(mouseValues[3].split(":")[1])));
                            keyMap.x = (toNearestFive(Integer.parseInt(mouseValues[2].split(":")[1]))) / viewPortWidth;
                            DecimalFormat df = new DecimalFormat("#.00");
                            keyMap.x = (Float.parseFloat(df.format(keyMap.x)));
                            keyMap.fixed = (false);
                            if (!heatmapResult.containsKey(keyMap)) {
                                heatmapResult.put(keyMap, 1);
                            } else {
                                heatmapResult.replace(keyMap, heatmapResult.get(keyMap) + 1);
                            }
                        }
                    }

                }
            }
        } catch (Exception ex) {
            System.out.println(ex);
        }
        for(Map.Entry<KeyMap, Integer> entry : heatmapResult.entrySet()) {
            ApiHeatmapGetDTO heatmapDTO = new ApiHeatmapGetDTO();
            heatmapDTO.setKeyMap(entry.getKey(), entry.getValue());
            results.add(heatmapDTO);
        }
        return results;
    }


    private LocalDateTime getTheDate(String val) {
        char suf = val.charAt(val.length() - 1);
        int day;
        if (suf != 't') {
            day = Integer.parseInt(val.substring(1, val.length() - 1));
        } else {
            day = -1;
        }
        switch (suf) {
            case 'h':
                day = -1;
                break;
            case 'w':
                day *= 7;
                break;
            case 'm':
                day *= 30;
                break;
            case 'y':
                day *= 365;
                break;
        }
        return LocalDateTime.now().minusDays(day);
    }

    private String getUrlExact(String val) {
        String temp;
        temp = val.replace("%3A", ":");
        return temp.replace("%2F", "/");
    }

    private static List<String> splitOnCommaOutsideBraces(String s, char div) {
        List<String> parts = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        int depth = 0;

        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '{' || c == '[' || c == '(') {
                depth++;
                cur.append(c);
            } else if (c == '}' || c == ']' || c == ')') {
                depth = Math.max(0, depth - 1);
                cur.append(c);
            } else if (c == div && depth == 0) {
                parts.add(cur.toString().trim());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        if (!cur.isEmpty()) parts.add(cur.toString().trim());
        return parts;
    }

    private static List<String> splitUrlAndProps(String s) {
        List<String> parts = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        int depth = 0;
        int cnt = 0;

        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if(c == '"') {
                cnt++;
                cur.append(c);
            } else if (c == '[') {
                depth++;
                cur.append(c);
            } else if (c == ']') {
                depth = Math.max(0, depth - 1);
                cur.append(c);
            } else if (c == ':' && depth == 0 && cnt % 2 == 0) {
                parts.add(cur.toString().trim());
                cur.setLength(0);
            } else {
                cur.append(c);
            }
        }
        if (!cur.isEmpty()) parts.add(cur.toString().trim());
        return parts;
    }

    private static int toNearestFive(int val) {
        int mod = val % 5;
        if(mod < 3) {
            return val - mod;
        } else {
            return val + (5 - mod);
        }
    }
}
